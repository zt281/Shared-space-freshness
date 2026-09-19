// DISPOSABLE DIAGNOSTIC: autonomous local publication/consumption, no orders.
// Measurement buffers are volatile; business journal/checkpoints are unchanged.
#include "durable_consumer.hpp"
#include "batch_publisher.hpp"
#include <algorithm>
#include <cerrno>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <sys/resource.h>
#include <time.h>
#include <unistd.h>

using Nano = std::int64_t;
namespace {
Nano clock_ns() {
  timespec value{};
  require(clock_gettime(CLOCK_MONOTONIC, &value) == 0, "monotonic clock");
  return value.tv_sec * 1000000000LL + value.tv_nsec;
}
void sleep_until(Nano when) {
  timespec value{when / 1000000000LL, when % 1000000000LL};
  int result;
  do { result = clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &value, nullptr); }
  while (result == EINTR);
  require(result == 0, "absolute monotonic wait");
}
std::int64_t cpu_us(const timeval& value) { return value.tv_sec * 1000000LL + value.tv_usec; }
struct Row {
  Nano planned = 0, started = 0, prepared = 0, publication_started = 0, completed = 0;
  Change event{};
  int outcome = 0; // 0 = not completed; 1 = completed and checked.
  int accepted = 0, terminal = 0; // 0 unstarted, 1 committed, 2 rejected, 3 unknown.
  Nano enqueue_returned = 0, result_observed = 0, sync_started = 0, synced = 0, published = 0;
};
void payload(std::ostream& out, const Change& event) {
  const auto& r = event.record;
  out << event.sequence << ',' << r.epoch << ',' << r.version << ',' << r.proof << ','
      << r.value_time << ',' << r.verified_time << ',' << r.received_time << ','
      << r.price << ',' << r.quantity << ',' << r.checksum << ',' << r.gap << ','
      << r.time_known << ',' << event.seal;
}
}

int main(int argc, char** argv) {
  try {
    require(argc == 9 || argc == 12, "capacity_probe ROLE ROOT NAME IDENTITY INDEX RATE COUNT IDLE_NS [QUEUE BATCH WAIT_NS]");
    const std::string role = argv[1];
    const std::filesystem::path root = argv[2];
    const Space::Location location{argv[3], root / "PROTOTYPE-events.bin", std::stoull(argv[4])};
    const auto index = std::stoull(argv[5]), rate = std::stoull(argv[6]), count = std::stoull(argv[7]);
    const Nano idle_ns = std::stoll(argv[8]);
    require(rate > 0 && count > 0 && count <= 100000 && idle_ns >= 0, "bounded diagnostic inputs");
    if (role == "unlink") { Space::unlink_named(location); return 0; }
    const bool batched = role == "batch", publisher = role == "publisher" || batched, durable = role == "durable";
    require(!batched || argc == 12, "explicit batch experiment values required");
    require(publisher || durable || role == "ordered", "diagnostic role");
    if (publisher) { Space creator(location, Space::Access::create); }
    Space space(location, publisher ? Space::Access::publisher : Space::Access::reader);
    std::unique_ptr<DurableConsumer> saved;
    std::unique_ptr<OrderedConsumer> ordered;
    const auto label = publisher ? std::string("publisher") : "consumer-" + std::to_string(index);
    const auto checkpoint = root / ("PROTOTYPE-consumer-" + std::to_string(index) + ".checkpoint");
    if (publisher) space.replace(0); // Initialization event is excluded from timed input.
    else if (durable) saved = std::make_unique<DurableConsumer>(space, checkpoint, index + 1, true);
    else ordered = std::make_unique<OrderedConsumer>(space, 4, false);
    std::vector<Change> delivered;
    delivered.reserve(1);
    if (!publisher) {
      const bool ok = durable ? saved->consume(0, 1, delivered) :
        ordered->consume(0, 1, [&](const Change& e) { delivered.push_back(e); return true; });
      require(ok && delivered.size() == 1 && delivered.front().sequence == 1, "initialization consumption");
    }
    const auto info = space.attachment();
    std::vector<Row> rows(count); // Allocation is outside the measured window.
    std::unique_ptr<BatchPublisher> batch;
    std::vector<BatchPublisher::Submission> submitted;
    submitted.reserve(count);
    if (batched) batch = std::make_unique<BatchPublisher>(space, std::stoull(argv[9]), std::stoull(argv[10]), std::stoull(argv[11]));
    std::cout << "{\"phase\":\"ready\",\"pid\":" << getpid() << ",\"address\":" << info.address
              << ",\"authority\":" << info.authority << ",\"head\":" << info.head << "}" << std::endl;
    Nano start = 0, window_end = 0, deadline = 0;
    require(static_cast<bool>(std::cin >> start >> window_end >> deadline), "single start barrier");
    require(clock_ns() < start && start < window_end && window_end < deadline, "future bounded window");
    for (std::uint64_t i = 0; i < count; ++i) {
      rows[i].planned = start + static_cast<Nano>(i * 1000000000ULL / rate);
      require(rows[i].planned < window_end, "planned arrival inside fixed window");
    }
    rusage before{}, after{};
    require(getrusage(RUSAGE_SELF, &before) == 0, "initial resource counters");
    space.reset_lock_metrics();
    sleep_until(start);
    std::uint64_t finished = 0, polls = 0, sequence_errors = 0, payload_errors = 0;
    std::string failure;
    const auto tick = [&]() { return std::max<Nano>(0, (clock_ns() - start) / 1000000LL); };
    try {
      if (batched) {
        for (std::uint64_t i = 0; i < count; ++i) {
          auto& row = rows[i];
          sleep_until(row.planned);
          if (clock_ns() >= deadline) break;
          row.started = clock_ns();
          const auto proposed = complete_record(info.authority, i + 2, tick());
          row.prepared = clock_ns();
          submitted.push_back(batch->submit(proposed));
          row.enqueue_returned = clock_ns();
          row.accepted = submitted.back().accepted;
          row.event = submitted.back().proposed;
        }
        // All scheduled inputs were offered before waiting for individual results.
        batch->close(deadline);
        for (std::size_t i = 0; i < submitted.size(); ++i) {
          const auto receipt = submitted[i].final.get();
          auto& row = rows[i];
          row.result_observed = clock_ns();
          row.publication_started = receipt.batch.write_started_ns;
          row.sync_started = receipt.batch.sync_started_ns;
          row.synced = receipt.batch.synced_ns;
          row.published = receipt.batch.published_ns;
          row.terminal = receipt.batch.state == Space::BatchState::committed ? 1 :
                         receipt.batch.state == Space::BatchState::unknown ? 3 : 2;
          if (row.terminal == 1) {
            row.completed = receipt.confirmed_by_ns; // Worker confirmation after save + shared publish, not enqueue return.
            row.outcome = 1; ++finished;
          }
        }
      } else if (publisher) {
        for (std::uint64_t i = 0; i < count; ++i) {
          auto& row = rows[i];
          sleep_until(row.planned); // Late starts never move subsequent planned arrivals.
          if (clock_ns() >= deadline) break;
          row.started = clock_ns();
          const Tick now = tick();
          space.prepare(now);
          row.prepared = clock_ns();
          row.publication_started = clock_ns();
          const bool ok = space.publish(now);
          row.completed = clock_ns();
          require(ok, "publication rejected; no reduced durability fallback");
          row.event = {i + 2, complete_record(info.authority, i + 2, now), 0};
          row.outcome = 1;
          row.accepted = row.terminal = 1;
          ++finished;
        }
      } else {
        while (finished < count && clock_ns() < deadline) {
          delivered.clear();
          const auto began = clock_ns();
          const Tick now = tick();
          const bool ok = durable ? saved->consume(now, 1, delivered) :
            ordered->consume(now, 1, [&](const Change& e) { delivered.push_back(e); return true; });
          const auto ended = clock_ns();
          ++polls;
          require(ok, durable ? "durable consumption: " + saved->error() : "ordered consumption failed");
          if (delivered.empty()) {
            if (idle_ns) sleep_until(std::min(deadline, ended + idle_ns));
            continue;
          }
          require(delivered.size() == 1, "one-event timing budget");
          const auto& event = delivered.front();
          if (event.sequence != finished + 2) ++sequence_errors;
          if (event.record.checksum != checksum(event.record) ||
              event.record.epoch != info.authority || event.record.version != event.sequence ||
              event.record.quantity != event.sequence || event.record.price != 100 + event.sequence) ++payload_errors;
          require(sequence_errors == 0 && payload_errors == 0, "sequence/payload validation");
          if (durable) require(saved->saved().cursor == event.sequence, "checkpoint confirmation cursor");
          auto& row = rows[finished];
          row.started = began;
          row.completed = ended; // Upper bound: checkpoint already synced; exact internal instant is unavailable.
          row.event = event;
          row.outcome = 1;
          ++finished;
        }
      }
    } catch (const std::exception& error) { failure = error.what(); }
    const auto measured_end = clock_ns();
    const auto locks = space.lock_metrics();
    const auto batch_totals = batch ? batch->metrics() : BatchPublisher::Metrics{};
    require(getrusage(RUSAGE_SELF, &after) == 0, "final resource counters");
    std::cout << "{\"phase\":\"measured\",\"completed\":" << finished
              << ",\"error\":" << std::quoted(failure) << "}" << std::endl;
    std::string save;
    require(static_cast<bool>(std::cin >> save) && save == "save", "final evidence barrier");
    // Only after every process finishes timing does the driver permit bulk evidence I/O.
    std::ofstream csv(root / (label + ".csv"));
    require(csv.good(), "measurement CSV");
    csv << "index,planned_ns,started_ns,prepared_ns,publication_started_ns,completed_ns,checkpoint_confirmed_by_ns,outcome,"
           "sequence,epoch,version,proof,value_ms,verified_ms,received_ms,price,quantity,checksum,gap,time_known,seal,"
           "accepted,terminal,enqueue_returned_ns,result_observed_ns,sync_started_ns,synced_ns,published_ns\n";
    for (std::uint64_t i = 0; i < count; ++i) {
      const auto& row = rows[i];
      csv << i << ',' << row.planned << ',' << row.started << ',' << row.prepared << ','
          << row.publication_started << ',' << row.completed << ',' << (durable ? row.completed : 0)
          << ',' << row.outcome << ',';
      payload(csv, row.event);
      csv << ',' << row.accepted << ',' << row.terminal << ',' << row.enqueue_returned << ',' << row.result_observed
          << ',' << row.sync_started << ',' << row.synced << ',' << row.published;
      csv << '\n';
    }
    csv.flush(); require(csv.good(), "complete measurement CSV");
    const auto final_info = space.attachment();
    std::ofstream stats(root / (label + ".json"));
    stats << "{\"role\":" << std::quoted(role) << ",\"pid\":" << getpid()
          << ",\"start_ns\":" << start << ",\"window_end_ns\":" << window_end
          << ",\"deadline_ns\":" << deadline << ",\"measured_end_ns\":" << measured_end
          << ",\"planned\":" << count << ",\"completed\":" << finished << ",\"polls\":" << polls
          << ",\"sequence_errors\":" << sequence_errors << ",\"payload_errors\":" << payload_errors
          << ",\"final_head\":" << final_info.head << ",\"error\":" << std::quoted(failure)
          << ",\"user_cpu_us\":" << cpu_us(after.ru_utime) - cpu_us(before.ru_utime)
          << ",\"system_cpu_us\":" << cpu_us(after.ru_stime) - cpu_us(before.ru_stime)
          << ",\"max_rss_kib_process_lifetime\":" << after.ru_maxrss
          << ",\"voluntary_context_switches\":" << after.ru_nvcsw - before.ru_nvcsw
          << ",\"involuntary_context_switches\":" << after.ru_nivcsw - before.ru_nivcsw
          << ",\"inblock\":" << after.ru_inblock - before.ru_inblock
          << ",\"oublock\":" << after.ru_oublock - before.ru_oublock
          << ",\"guard_calls\":" << locks.calls << ",\"guard_wait_ns\":" << locks.wait_ns
          << ",\"guard_max_wait_ns\":" << locks.max_ns
          << ",\"batch_accepted\":" << batch_totals.accepted << ",\"batch_rejected\":" << batch_totals.rejected
          << ",\"batch_unknown\":" << batch_totals.unknown << ",\"batch_committed\":" << batch_totals.committed
          << ",\"batch_count\":" << batch_totals.batches << ",\"batch_syncs\":" << batch_totals.syncs
          << ",\"batch_max_pending\":" << batch_totals.max_pending << "}\n";
    stats.flush(); require(stats.good(), "resource evidence");
    std::cout << "{\"phase\":\"saved\"}" << std::endl;
    return failure.empty() ? 0 : 2;
  } catch (const std::exception& error) {
    std::cout << "{\"phase\":\"error\",\"message\":" << std::quoted(std::string(error.what())) << "}" << std::endl;
    return 2;
  }
}
