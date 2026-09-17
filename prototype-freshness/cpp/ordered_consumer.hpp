#pragma once
#include "consumer.hpp"
#include "space.hpp"

// Disposable per-consumer progress and recovery experiment. No networking here.
class OrderedConsumer {
  Space& space;
  Consumer policy;
  const std::uint64_t lag_limit;
  std::uint64_t cursor = 0, processed = 0, journal_reads = 0;
  std::uint64_t alerts = 0, cancellation_attempts = 0;
  bool recovering = false, processing_failed = false;

  View assess(const Changes& changes, Tick now) {
    const auto backlog = changes.head >= cursor ? changes.head - cursor : 0;
    if (!changes.complete || !changes.latest.usable() || backlog >= lag_limit || processing_failed) {
      if (!recovering) { ++alerts; ++cancellation_attempts; }
      recovering = true;
    }
    auto input = changes.latest;
    if (!changes.complete || processing_failed || backlog >= lag_limit)
      input.validity = Validity::gap;
    policy.observe(input, now);
    if (recovering && changes.complete && !processing_failed && backlog == 0 && policy.allowed(input, now))
      recovering = false;
    return input;
  }
public:
  struct Status {
    View source;
    std::uint64_t cursor, head, backlog, processed, journal_reads, alerts, cancellation_attempts;
    bool allowed, recovering, complete;
  };
  explicit OrderedConsumer(Space& input, std::uint64_t threshold = 4)
      : space(input), lag_limit(threshold) { require(threshold > 0, "positive demo lag threshold"); }
  Status status(Tick now) {
    const auto changes = space.read_after(cursor, 0, now);
    const auto input = assess(changes, now);
    const bool allowed = changes.complete && cursor == changes.head && !processing_failed && policy.allowed(input, now);
    return {changes.latest, cursor, changes.head, changes.head >= cursor ? changes.head - cursor : 0,
            processed, journal_reads, alerts, cancellation_attempts, allowed, recovering, changes.complete};
  }
  template<class Process> bool consume(Tick now, std::size_t budget, Process process) {
    const auto changes = space.read_after(cursor, budget, now);
    assess(changes, now);
    if (!changes.complete) return false;
    journal_reads += changes.from_journal;
    for (const auto& event : changes.events) {
      if (event.sequence != cursor + 1 || !process(event)) {
        processing_failed = true;
        status(now);
        return false;
      }
      ++cursor; ++processed; // Progress only follows successful processing.
      processing_failed = false;
    }
    status(now);
    return true;
  }
  Consumer::RecoveryTicket recovery_ticket(Tick now) {
    auto changes = space.read_after(cursor, 0, now);
    return policy.recovery_ticket(assess(changes, now), now);
  }
  bool reconcile(const Consumer::RecoveryTicket& ticket, Tick now) {
    const auto changes = space.read_after(cursor, 0, now);
    const auto input = assess(changes, now);
    if (!changes.complete || cursor != changes.head || processing_failed) return false;
    return policy.reconcile(ticket, input, now);
  }
  void stop() { policy.stop(); }
  void resume() { policy.resume(); }
  bool issue(Tick now) {
    auto changes = space.read_after(cursor, 0, now);
    const auto input = assess(changes, now);
    return changes.complete && cursor == changes.head && !processing_failed && policy.issue(input, now);
  }
  std::string execute(Tick now) {
    auto changes = space.read_after(cursor, 0, now);
    const auto input = assess(changes, now);
    if (!changes.complete || cursor != changes.head || processing_failed) return "not_ready";
    return policy.execute(input, now);
  }
};
