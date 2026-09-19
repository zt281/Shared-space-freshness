#pragma once
#include "ordered_consumer.hpp"
#include <filesystem>

// PROTOTYPE: pure accumulation and its cursor commit together. No broker calls.
class DurableConsumer {
public:
  struct State {
    std::uint64_t magic = 0x545943484543484bULL, layout = 1, space = 0, consumer = 0;
    std::uint64_t revision = 0, cursor = 0, processed = 0, last_event_seal = 0;
    std::uint64_t quantity_sum = 0, price_sum = 0, chain = 1469598103934665603ULL;
    std::uint64_t stopped = 0, intent_epoch = 0;
    Tick intent_expires = 0;
    std::uint64_t intent_outcome = 0, seal = 0;
  };
private:
  Space& space;
  OrderedConsumer ordered;
  std::filesystem::path path;
  int lease = -1, directory = -1, crash_point = -1;
  State state;
  bool failed = false;
  std::string failure;
  void save(State next, bool create = false);
  void persist_control();
  void trigger(int point) const;
  friend class experiment::Faults;
public:
  DurableConsumer(Space&, const std::filesystem::path&, std::uint64_t identity, bool create);
  ~DurableConsumer();
  DurableConsumer(const DurableConsumer&) = delete;
  DurableConsumer& operator=(const DurableConsumer&) = delete;
  OrderedConsumer::Status status(Tick now);
  bool consume(Tick now, std::size_t budget, std::vector<Change>& processed);
  Consumer::RecoveryTicket recovery_ticket(Tick now) { return ordered.recovery_ticket(now); }
  bool reconcile(const Consumer::RecoveryTicket& ticket, Tick now) {
    return !failed && ordered.reconcile(ticket, now);
  }
  void stop();
  void resume();
  bool issue(Tick now);
  std::string execute(Tick now);
  const State& saved() const { return state; }
  const std::string& error() const { return failure; }
};
