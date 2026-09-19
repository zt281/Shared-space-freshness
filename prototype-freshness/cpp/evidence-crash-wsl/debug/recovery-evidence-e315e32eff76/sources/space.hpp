#pragma once
#include "model.hpp"
#include <filesystem>
#include <vector>

struct Change {
  std::uint64_t sequence = 0;
  Record record{};
  std::uint64_t seal = 0;
};
struct Changes {
  View latest;
  std::uint64_t head = 0;
  std::vector<Change> events;
  std::size_t from_journal = 0;
  bool complete = true;
};

namespace experiment { class Faults; }
// Single authoritative writer; reads are complete copied snapshots.
// Legacy scenarios inherit a mapping; named scenarios open it independently.
class Space {
  struct Shared;
  class Guard;
  Shared* shared = nullptr;
  Record draft{};
  bool prepared = false;
  int journal = -1;
  int region_fd = -1;
  bool named = false;
  std::uint64_t writer_epoch = 0;
  int writer_pid = 0;
  int crash_point = -1; // Only the experiment fault seam can arm this.
  bool append(const Record& record); // Called only under Guard.
  void install(const Record& record); // Called only under Guard.
  void recover_journal(); // Called under Guard and the exclusive writer lease.
  View current(Tick now) const; // Called only under Guard.
  void check_writer() const; // Called only under Guard.
  void claim_writer();
  friend class experiment::Faults;
public:
  enum class Access { create, reader, publisher };
  struct Location {
    std::string name;
    std::filesystem::path journal;
    std::uint64_t identity;
    std::uintptr_t address = 0; // Experiment only; never a shared object identity.
  };
  struct Attachment {
    std::uint64_t identity, authority, head, publisher_start;
    int publisher_pid;
    std::uintptr_t address;
  };
  static constexpr std::size_t buffer_capacity = 8; // Demo, not a capacity target.
  explicit Space(const std::filesystem::path& prototype_journal = {});
  Space(const Location& location, Access access);
  Attachment attachment();
  // Experiment owner calls this after all users exit; never deletes a journal.
  static void unlink_named(const Location& location);
  ~Space();
  Space(const Space&) = delete;
  Space& operator=(const Space&) = delete;
  View read(Tick now);
  Changes read_after(std::uint64_t cursor, std::size_t budget, Tick now);
  void prepare(Tick now);
  bool publish(Tick now);
  void replace(Tick now);
  void verify(Tick now);
  void replay(Tick now);
  void heartbeat();
  void restart();
};
