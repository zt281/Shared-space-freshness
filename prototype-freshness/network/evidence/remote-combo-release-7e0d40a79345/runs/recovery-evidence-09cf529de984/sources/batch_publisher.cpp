#include "batch_publisher.hpp"
#include "diagnostic_trace.hpp"
#include <chrono>

namespace {
std::uint64_t now_ns() {
  timespec value{};
  require(clock_gettime(CLOCK_MONOTONIC, &value) == 0, "batch clock");
  return value.tv_sec * 1000000000ULL + value.tv_nsec;
}
}
BatchPublisher::BatchPublisher(Space& source, std::size_t bound, std::size_t batch, std::uint64_t wait)
  : space(source), initial(source.batch_seed()), identity(source.attachment().identity), capacity(bound), max_batch(batch), wait_ns(wait),
    next_sequence(initial.sequence + 1), next_version(initial.record.version + 1) {
  require(capacity > 0 && max_batch > 0 && max_batch <= Space::buffer_capacity && max_batch <= capacity,
          "bounded batch experiment values");
  worker = std::thread([this] { run(); });
}
BatchPublisher::~BatchPublisher() { close(); }
BatchPublisher::Submission BatchPublisher::submit(const Record& record) {
  std::unique_lock lock(mutex);
  auto event = Space::proposal(next_sequence, record);
  Item item{event, now_ns(), diagnostic::request, {}};
  auto future = item.promise.get_future();
  const bool invalid = record.epoch != initial.record.epoch || record.version != next_version ||
                       record.checksum != checksum(record) || record.gap || !record.time_known;
  if (closing || restricted || pending >= capacity || invalid) {
    ++totals.rejected;
    restricted = true;
    lock.unlock();
    space.restrict_ingress(); // No queue/disk lock: restriction precedes final failed receipt.
    item.promise.set_value({{}, event, item.enqueued, now_ns(), false});
    changed.notify_all();
    return {event, false, std::move(future)};
  }
  ++next_sequence; ++next_version; ++pending; ++totals.accepted;
  totals.max_pending = std::max(totals.max_pending, pending);
  diagnostic::mark("batch_admitted", identity, record.epoch, event.sequence, pending);
  queue.push_back(std::move(item));
  lock.unlock();
  changed.notify_one();
  return {event, true, std::move(future)};
}
void BatchPublisher::close(std::uint64_t deadline_ns) {
  { std::lock_guard lock(mutex); closing = true; if (deadline_ns) drain_deadline_ns = deadline_ns; }
  changed.notify_all();
  if (worker.joinable()) worker.join();
}
void BatchPublisher::reject_input(std::size_t count) {
  { std::lock_guard lock(mutex); restricted = true; totals.rejected += count; }
  space.restrict_ingress();
  changed.notify_all();
}
BatchPublisher::Metrics BatchPublisher::metrics() { std::lock_guard lock(mutex); return totals; }
void BatchPublisher::run() {
  for (;;) {
    std::vector<Item> batch;
    {
      std::unique_lock lock(mutex);
      changed.wait(lock, [&] { return closing || !queue.empty(); });
      if (queue.empty() && closing) return;
      if (closing && drain_deadline_ns && now_ns() >= drain_deadline_ns) {
        std::deque<Item> abandoned;
        while (!queue.empty()) {
          abandoned.push_back(std::move(queue.front()));
          queue.pop_front(); --pending; ++totals.rejected;
        }
        restricted = true;
        lock.unlock();
        space.restrict_ingress();
        for (auto& item : abandoned)
          item.promise.set_value({{}, item.event, item.enqueued, now_ns(), true});
        return;
      }
      const auto until = std::chrono::steady_clock::time_point(std::chrono::nanoseconds(queue.front().enqueued + wait_ns));
      changed.wait_until(lock, until, [&] { return closing || restricted || queue.size() >= max_batch; });
      if (closing && drain_deadline_ns && now_ns() >= drain_deadline_ns) continue;
      while (!queue.empty() && batch.size() < max_batch) {
        batch.push_back(std::move(queue.front())); queue.pop_front();
      }
    }
    std::vector<Change> events;
    for (const auto& item : batch) {
      diagnostic::Request scope(item.request);
      diagnostic::mark("batch_dequeued", identity, item.event.record.epoch, item.event.sequence, batch.size(), item.enqueued);
      events.push_back(item.event);
    }
    auto result = space.publish_admitted_batch(events);
    if (result.state != Space::BatchState::committed) {
      { std::lock_guard lock(mutex); restricted = true; }
      space.restrict_ingress(); // Final failure result cannot precede shared restriction.
    }
    const auto confirmed = now_ns();
    {
      std::lock_guard lock(mutex);
      ++totals.batches;
      if (result.synced_ns) ++totals.syncs;
      if (result.state == Space::BatchState::committed) totals.committed += batch.size();
      else if (result.state == Space::BatchState::unknown) totals.unknown += batch.size();
      else totals.rejected += batch.size();
      pending -= batch.size();
      for (auto& item : batch)
        item.promise.set_value({result, item.event, item.enqueued, confirmed, true});
      if (result.state != Space::BatchState::committed) {
        restricted = true;
        // These accepted entries were never attempted; explicitly reject, do not retry.
        while (!queue.empty()) {
          auto& item = queue.front();
          item.promise.set_value({{}, item.event, item.enqueued, now_ns(), true});
          queue.pop_front(); --pending; ++totals.rejected;
        }
      }
    }
  }
}
