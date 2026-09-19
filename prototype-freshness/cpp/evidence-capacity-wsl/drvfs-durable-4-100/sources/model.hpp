#pragma once
#include <cstdint>
#include <stdexcept>
#include <string>

using Tick = std::int64_t;
constexpr Tick warning_age = 700, expiry_age = 1000;
constexpr Tick stable_period = 200, command_lifetime = 500;
constexpr std::uint64_t checksum_salt = 0xCAFE1234ULL;

inline void require(bool condition, const std::string& message) {
  if (!condition) throw std::runtime_error(message);
}

struct Record {
  std::uint64_t epoch = 1, version = 1, proof = 1;
  Tick value_time = 0, verified_time = 0, received_time = 0;
  std::uint64_t price = 100, quantity = 1, checksum = 0;
  bool gap = false, time_known = true;
};
inline std::uint64_t checksum(const Record& r) {
  return r.price ^ (r.quantity << 16) ^ r.version ^ checksum_salt;
}
inline Record complete_record(std::uint64_t epoch, std::uint64_t version, Tick now) {
  Record r;
  r.epoch = epoch;
  r.version = r.proof = version;
  r.value_time = r.verified_time = r.received_time = now;
  r.price = 100 + version;
  r.quantity = version;
  r.checksum = checksum(r);
  return r;
}
enum class Validity { valid, warning, expired, unknown, gap, old_epoch, damaged };
inline const char* label(Validity v) {
  switch (v) {
    case Validity::valid: return "valid";
    case Validity::warning: return "warning";
    case Validity::expired: return "expired";
    case Validity::unknown: return "unknown";
    case Validity::gap: return "gap";
    case Validity::old_epoch: return "old_epoch";
    case Validity::damaged: return "damaged";
  }
  return "unknown";
}
struct View {
  Record record;
  std::uint64_t authority, heartbeats;
  bool poisoned;
  Validity validity;
  Tick age;
  bool usable() const { return validity == Validity::valid || validity == Validity::warning; }
};
