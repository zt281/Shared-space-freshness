#pragma once
// DISPOSABLE experiment: fixed small batches, one local publisher process.
#include "space.hpp"
#include <condition_variable>
#include <deque>
#include <future>
#include <thread>

class BatchPublisher {
public:
  struct Receipt {
    Space::BatchResult batch;
    Change proposed;
    std::uint64_t enqueued_ns = 0, confirmed_by_ns = 0;
    bool accepted = false;
  };
  struct Submission { Change proposed; bool accepted; std::future<Receipt> final; };
  struct Metrics { std::uint64_t accepted, rejected, committed, unknown, batches, syncs, max_pending; };
  BatchPublisher(Space&, std::size_t capacity, std::size_t max_batch, std::uint64_t wait_ns);
  ~BatchPublisher();
  Submission submit(const Record&); // No disk wait; immutable identity on admission.
  void close(std::uint64_t deadline_ns = 0); // No new disk batch after deadline; active syscall may overrun.
  Change seed() const { return initial; }
  Metrics metrics();
private:
  struct Item { Change event; std::uint64_t enqueued; std::promise<Receipt> promise; };
  Space& space;
  const Change initial;
  const std::size_t capacity, max_batch;
  const std::uint64_t wait_ns;
  std::mutex mutex;
  std::condition_variable changed;
  std::deque<Item> queue;
  std::thread worker;
  bool closing = false, restricted = false;
  std::uint64_t next_sequence, next_version, pending = 0;
  std::uint64_t drain_deadline_ns = 0;
  Metrics totals{};
  void run();
};
