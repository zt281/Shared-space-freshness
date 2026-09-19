#pragma once
#include "quic_wire.hpp"
#include <functional>

namespace quic_demo {
// Receiver-owned durable replica; strategy consumers use ReadableSpace only.
// One source log per object, one local provider process, same-host local ABI.
class ReplicaSpace final : public ReadableSpace {
  struct Shared;
  class Guard;
  Shared* shared = nullptr;
  int region = -1, journal = -1;
  bool writer = false;
  std::uint64_t log_id = 0;
  std::string name;
  Change load(std::uint64_t sequence);
  void install(const Change&);
  View view(Tick now) const;
public:
  static constexpr std::size_t disk_bytes = 4 + (2 + record_words)*8;
  ReplicaSpace(const std::filesystem::path& root, const std::string& region_name,
               std::uint64_t log_identity, bool provide, bool create, std::uintptr_t address = 0);
  ~ReplicaSpace();
  Attachment attachment() override;
  View read(Tick now) override;
  Changes read_after(std::uint64_t cursor, std::size_t budget, Tick now) override;
  void restrict(bool damaged = false);
  void activate();
  // Hook after complete pwrite but before sync permits a deterministic pause.
  // crash: 1 half record; 2 full write; 3 sync; 4 shared publication.
  bool accept(const Change&, int crash = 0, bool sync_error = false,
              const std::function<void()>& before_sync = {});
  static void unlink(const std::string& name);
};
}
