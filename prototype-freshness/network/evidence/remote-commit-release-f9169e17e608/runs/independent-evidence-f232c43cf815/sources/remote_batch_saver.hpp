#pragma once
// DISPOSABLE experiment: bounded remote save queue; one receiver process, one saver thread per log.
#include "quic_replica.hpp"
#include <condition_variable>
#include <deque>
#include <functional>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

namespace quic_demo {
// Thread ownership: the application thread alone calls admit/reset/metrics/arm_* and owns the
// received/durable/visible watermarks, gap detection policy and progress replies. The saver thread
// only runs pwrite + fdatasync + the bounded shared-lock install inside ReplicaSpace, and reports
// each finished batch through the completion callback, which is drained as an ordinary application
// job. Nothing in this class touches connections, streams or control frames.
class RemoteBatchSaver {
public:
  enum class Admission { admitted, duplicate, gap, full };
  struct Done { Change event; std::uint64_t generation; };
  using Completion = std::function<void(std::vector<Done>, std::string error)>;
  struct Metrics {
    std::uint64_t admitted = 0, duplicates = 0, completed = 0, batches = 0, syncs = 0, max_pending = 0, pending = 0;
    bool restricted = false;
  };
  RemoteBatchSaver(ReplicaSpace&, std::size_t capacity, std::size_t max_batch, std::uint64_t wait_ns, Completion);
  ~RemoteBatchSaver();
  // Application thread. duplicate/gap compare against the confirmed prefix plus the queued/inflight
  // suffix; full means the bounded queue (or the overflow latch) refused a fresh sequence.
  Admission admit(const Change&, std::uint64_t generation);
  void reset(); // A new subscription generation clears the overflow latch; the admitted prefix keeps draining.
  void arm_crash(int point);   // Batch-level fault 0..6 applied to the next dequeued batch; idle queue required.
  void arm_sync_error();       // The next dequeued batch fails its fdatasync; idle queue required.
  void arm_gate(int notify_fd, int release_fd); // One-shot pre-dequeue gate; idle queue required.
  bool gate_armed();             // Any thread; the caller owns the release pipe's write end.
  Metrics metrics();
  void close(); // Drain admitted records to disk, then join the saver thread.
private:
  struct Item { Change event; std::uint64_t generation, enqueued_ns; };
  ReplicaSpace& replica;
  const std::uint64_t identity;
  const std::size_t capacity, max_batch;
  const std::uint64_t wait_ns;
  Completion completion;
  std::mutex mutex;
  std::condition_variable changed;
  std::deque<Item> queue;
  std::vector<Item> inflight; // Batch currently inside pwrite/fdatasync/publish.
  std::thread worker;
  bool closing = false, restricted = false;
  std::uint64_t confirmed_head;
  int armed_crash = -1;
  bool armed_sync_error = false;
  int gate_notify = -1, gate_release = -1;
  Metrics totals;
  void run();
};
}
