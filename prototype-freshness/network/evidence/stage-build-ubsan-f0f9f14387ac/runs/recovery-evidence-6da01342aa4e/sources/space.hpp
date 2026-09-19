#pragma once
#include "model.hpp"
#include <filesystem>
#include <vector>
#include <atomic>
#include <mutex>

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
class BatchPublisher;
// The consumer contract does not expose replication or socket details.
class ReadableSpace {
public:
  struct Attachment {
    std::uint64_t identity, authority, head, publisher_start;
    int publisher_pid;
    std::uintptr_t address;
  };
  virtual ~ReadableSpace() = default;
  virtual Attachment attachment() = 0;
  virtual View read(Tick now) = 0;
  virtual Changes read_after(std::uint64_t cursor, std::size_t budget, Tick now) = 0;
};
// Single authoritative writer; reads are complete copied snapshots.
// Legacy scenarios inherit a mapping; named scenarios open it independently.
class Space : public ReadableSpace {
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
  // Only named writers use this process-local mutex. Anonymous fork scenarios
  // retain their original process-shared Guard for the entire write operation.
  std::mutex writer_mutex;
  std::atomic<std::uint64_t> lock_calls{0}, lock_wait_ns{0}, lock_max_ns{0};
  int batch_crash_point = -1, batch_gate_notify = -1, batch_gate_release = -1;
  bool batch_fail_sync = false;
  std::unique_lock<std::mutex> serialize_writer();
  bool append(const Record& record); // Called only under Guard.
  void install(const Record& record); // Called only under Guard.
  void recover_journal(); // Called under Guard and the exclusive writer lease.
  View current(Tick now) const; // Called only under Guard.
  void check_writer() const; // Called only under Guard.
  void claim_writer();
  friend class experiment::Faults;
  friend class BatchPublisher;
public:
  enum class BatchState { rejected = 0, committed = 1, unknown = 2 };
  struct BatchResult {
    BatchState state = BatchState::rejected;
    std::uint64_t write_started_ns = 0, sync_started_ns = 0, synced_ns = 0,
                  published_ns = 0, returned_ns = 0;
    std::size_t count = 0;
  };
  struct LockMetrics { std::uint64_t calls, wait_ns, max_ns; };
  enum class Access { create, reader, publisher };
  struct Location {
    std::string name;
    std::filesystem::path journal;
    std::uint64_t identity;
    std::uintptr_t address = 0; // Experiment only; never a shared object identity.
  };
  using Attachment = ReadableSpace::Attachment;
  static constexpr std::size_t buffer_capacity = 8; // Demo, not a capacity target.
  LockMetrics lock_metrics() const;
  void reset_lock_metrics(); // Diagnostic barrier only: no active calls.
  static Change proposal(std::uint64_t sequence, const Record& record);
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
private:
  // Queue-only entrance: accepted records may drain after an admission gap.
  // Nobody may use a high head alone as proof that their proposal was saved.
  Change batch_seed();
  BatchResult publish_admitted_batch(const std::vector<Change>& events);
  void restrict_ingress();
};
