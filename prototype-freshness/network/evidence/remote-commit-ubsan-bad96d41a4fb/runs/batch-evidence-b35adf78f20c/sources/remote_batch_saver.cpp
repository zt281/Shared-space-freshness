#include "remote_batch_saver.hpp"
#include "diagnostic_trace.hpp"
#include <cerrno>
#include <chrono>
#include <optional>
#include <stdexcept>
#include <unistd.h>

namespace quic_demo {
RemoteBatchSaver::RemoteBatchSaver(ReplicaSpace& space, std::size_t bound, std::size_t batch,
                                   std::uint64_t wait, Completion done)
    : replica(space), identity(space.attachment().identity), capacity(bound), max_batch(batch),
      wait_ns(wait), completion(std::move(done)), confirmed_head(space.attachment().head) {
  require(capacity > 0 && max_batch > 0 && max_batch <= capacity, "bounded remote save experiment values");
  worker = std::thread([this] { run(); });
}
RemoteBatchSaver::~RemoteBatchSaver() { close(); }
RemoteBatchSaver::Admission RemoteBatchSaver::admit(const Change& e, std::uint64_t generation) {
  std::unique_lock lock(mutex);
  const auto pending = queue.size() + inflight.size();
  const auto next = confirmed_head + pending + 1;
  if (e.sequence > next) return Admission::gap;
  if (e.sequence == next) {
    if (restricted || closing) return Admission::full;
    if (pending >= capacity) { // Temporary pressure, not a save failure: latch and let the caller close the connection.
      restricted = true;
      return Admission::full;
    }
    queue.push_back({e, generation, diagnostic::now_ns()});
    ++totals.admitted;
    totals.max_pending = std::max(totals.max_pending, queue.size() + inflight.size());
    diagnostic::mark("remote_save_admitted", identity, e.record.epoch, e.sequence, queue.size() + inflight.size());
    lock.unlock();
    changed.notify_one();
    return Admission::admitted;
  }
  // Duplicate range: identical retained content required, otherwise latch damaged like accept().
  auto same = [&](const Change& o) { return record_words_of(o) == record_words_of(e); };
  std::optional<bool> identical;
  for (const auto& item : inflight)
    if (item.event.sequence == e.sequence) identical = same(item.event);
  for (const auto& item : queue)
    if (item.event.sequence == e.sequence) identical = same(item.event);
  if (!identical) { // Already installed prefix: compare against the durable journal, lock-free pread.
    lock.unlock();
    const bool match = replica.identical(e.sequence, e);
    lock.lock();
    identical = match;
  }
  if (!*identical) {
    lock.unlock();
    replica.restrict(true);
    throw std::runtime_error("conflicting replica duplicate");
  }
  ++totals.duplicates;
  return Admission::duplicate;
}
void RemoteBatchSaver::reset() {
  std::lock_guard lock(mutex);
  restricted = false; // confirmed_head/queue stay authoritative; replayed duplicates compare by content.
}
void RemoteBatchSaver::arm_crash(int point) {
  std::lock_guard lock(mutex);
  require(point >= 0 && point <= 6 && queue.empty() && inflight.empty() && armed_crash < 0 && !armed_sync_error,
          "idle remote batch crash seam");
  armed_crash = point;
}
void RemoteBatchSaver::arm_sync_error() {
  std::lock_guard lock(mutex);
  require(queue.empty() && inflight.empty() && !armed_sync_error && armed_crash < 0, "idle remote sync fault seam");
  armed_sync_error = true;
}
void RemoteBatchSaver::arm_gate(int notify_fd, int release_fd) {
  std::lock_guard lock(mutex);
  require(queue.empty() && inflight.empty() && gate_notify < 0, "idle remote gate seam");
  gate_notify = notify_fd;
  gate_release = release_fd;
}
bool RemoteBatchSaver::gate_armed() {
  std::lock_guard lock(mutex);
  return gate_release >= 0;
}
RemoteBatchSaver::Metrics RemoteBatchSaver::metrics() {
  std::lock_guard lock(mutex);
  auto out = totals;
  out.pending = queue.size() + inflight.size();
  out.restricted = restricted;
  return out;
}
void RemoteBatchSaver::close() {
  { std::lock_guard lock(mutex); closing = true; }
  changed.notify_all();
  if (worker.joinable()) worker.join();
}
void RemoteBatchSaver::run() {
  for (;;) {
    std::vector<Item> batch;
    int crash;
    bool fail_sync;
    {
      std::unique_lock lock(mutex);
      changed.wait(lock, [&] { return closing || !queue.empty(); });
      if (queue.empty()) return; // closing with a fully drained queue.
      if (gate_notify >= 0) { // One-shot deterministic pre-dequeue hold (remote_gate).
        const auto notify = gate_notify;
        const auto release = gate_release;
        lock.unlock();
        const char ready = 'S';
        require(write(notify, &ready, 1) == 1, "remote gate signal");
        char token = 0;
        ssize_t n;
        do { n = ::read(release, &token, 1); } while (n < 0 && errno == EINTR);
        require(n == 1 && token == 'G', "remote gate release");
        lock.lock();
        gate_notify = gate_release = -1;
      }
      const auto until = std::chrono::steady_clock::time_point(std::chrono::nanoseconds(queue.front().enqueued_ns + wait_ns));
      changed.wait_until(lock, until, [&] { return closing || queue.size() >= max_batch; });
      while (!queue.empty() && batch.size() < max_batch) {
        batch.push_back(std::move(queue.front()));
        queue.pop_front();
      }
      inflight = batch;
      crash = armed_crash;
      armed_crash = -1;
      fail_sync = armed_sync_error;
      armed_sync_error = false;
    }
    for (const auto& item : batch)
      diagnostic::mark("remote_save_dequeued", identity, item.event.record.epoch, item.event.sequence,
                       batch.size(), item.enqueued_ns);
    std::vector<Change> events;
    for (const auto& item : batch) events.push_back(item.event);
    std::uint64_t new_head = 0;
    std::string error;
    try {
      new_head = replica.accept_batch(events, crash, fail_sync, {});
    } catch (const std::exception& e) {
      error = e.what();
    }
    std::vector<Done> done;
    for (const auto& item : batch) done.push_back({item.event, item.generation});
    {
      std::lock_guard lock(mutex);
      ++totals.batches;
      if (new_head) ++totals.syncs;
      if (error.empty()) {
        totals.completed += batch.size();
        if (new_head) confirmed_head = new_head;
      } else {
        restricted = true; // Save failure stays latched; the admitted suffix is reported, not retried.
        while (!queue.empty()) {
          done.push_back({queue.front().event, queue.front().generation});
          queue.pop_front();
        }
      }
      inflight.clear();
    }
    completion(std::move(done), error);
  }
}
}
