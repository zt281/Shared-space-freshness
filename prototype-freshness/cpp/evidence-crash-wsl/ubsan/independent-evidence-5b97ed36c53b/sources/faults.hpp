#pragma once
#include "space.hpp"
class DurableConsumer;
// Internal experiment seam, never included by the consumer module.
// Only fault experiments may bypass normal publication rules.
namespace experiment {
class Faults {
public:
  static void reset(Space&, Tick);
  static void gap(Space&);
  static void unknown_time(Space&);
  static void truncate_journal(Space&, std::uint64_t remaining_records);
  static void limit_journal(Space&, std::uint64_t maximum_records);
  // 0 before write, 1 partial write, 2 before sync, 3 after sync,
  // 4 after ring, 5 after head, 6 torn snapshot, 7 complete snapshot.
  static void publication_crash(Space&, int point);
  static void checkpoint_crash(DurableConsumer&, int point);
  [[noreturn]] static void crash(Space&);
};
}
