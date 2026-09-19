#pragma once
#include "space.hpp"
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
  [[noreturn]] static void crash(Space&);
};
}
