#pragma once
#include "model.hpp"

// Input is a current shared-space observation, never a transport status.
// All decision operations observe their input themselves; no call-order precondition.
class Consumer {
  friend class OrderedConsumer;
  friend class DurableConsumer;
  inline static std::uint64_t next_identity = 0; // Single-threaded experiment driver.
  std::uint64_t identity = ++next_identity;
  bool reconciled = true, stopped = false, last_usable = true;
  Tick ready_at = 0;
  std::uint64_t epoch = 1, recovery = 0;
  struct Intent { std::uint64_t epoch; Tick expires; std::string result; };
  Intent intent{0, 0, "none"};
  struct Control { bool stopped; std::uint64_t epoch; Tick expires; std::string outcome; };
  Control saved_control() const { return {stopped, intent.epoch, intent.expires, intent.result}; }
  void restore_control(const Control& control) {
    stopped = control.stopped;
    intent = {control.epoch, control.expires,
              control.outcome == "pending" ? "abandoned_restart" : control.outcome};
    reconciled = last_usable = false;
    ready_at = -1; // A checkpoint never restores permission to trade.
  }
  static bool usable(const View& v, Tick now) {
    // Cached valid/warning labels do not extend freshness with the passing of time.
    return v.usable() && v.record.epoch == v.authority &&
           now >= v.record.verified_time && now - v.record.verified_time < expiry_age;
  }
public:
  class RecoveryTicket {
    std::uint64_t consumer, epoch, recovery;
    RecoveryTicket(std::uint64_t c, std::uint64_t e, std::uint64_t r)
        : consumer(c), epoch(e), recovery(r) {}
    friend class Consumer;
  };
  explicit Consumer(bool startup_reconciled = true)
      : reconciled(startup_reconciled), last_usable(startup_reconciled),
        ready_at(startup_reconciled ? 0 : -1) {}
  Consumer(const Consumer&) = delete;
  Consumer& operator=(const Consumer&) = delete;
  Consumer(Consumer&&) = delete;
  Consumer& operator=(Consumer&&) = delete;
  void observe(const View& v, Tick now) {
    const bool fresh = usable(v, now);
    if (v.authority != epoch || (!fresh && last_usable)) {
      ++recovery;
      reconciled = false;
      ready_at = -1;
      epoch = v.authority;
    }
    if (!fresh) { reconciled = false; ready_at = -1; }
    if (fresh && ready_at < 0) ready_at = now + stable_period;
    last_usable = fresh;
  }
  RecoveryTicket recovery_ticket(const View& v, Tick now) {
    observe(v, now);
    return {identity, epoch, recovery};
  }
  bool reconcile(const RecoveryTicket& ticket, const View& v, Tick now) {
    observe(v, now);
    if (!usable(v, now) || ticket.consumer != identity ||
        ticket.epoch != epoch || ticket.recovery != recovery) return false;
    reconciled = true;
    return true;
  }
  void stop() { stopped = true; }
  void resume() { stopped = false; }
  bool allowed(const View& v, Tick now) {
    observe(v, now);
    return usable(v, now) && reconciled && !stopped && ready_at >= 0 && now >= ready_at;
  }
  bool issue(const View& v, Tick now) {
    if (!allowed(v, now) || intent.result == "pending" || intent.result == "unknown") return false;
    intent = {v.authority, now + command_lifetime, "pending"};
    return true;
  }
  std::string execute(const View& v, Tick now) {
    const bool ready = allowed(v, now);
    if (intent.result != "pending") return "no_resubmit";
    if (now >= intent.expires) return intent.result = "expired";
    if (intent.epoch != v.authority) return intent.result = "old_epoch";
    if (!ready) return intent.result = "not_ready";
    return intent.result = "unknown"; // Simulated call; no broker or exchange.
  }
};
