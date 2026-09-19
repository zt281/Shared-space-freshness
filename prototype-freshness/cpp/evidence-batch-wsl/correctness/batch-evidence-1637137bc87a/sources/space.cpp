#include "space.hpp"
#include "faults.hpp"
#include <cerrno>
#include <cstddef>
#include <cstring>
#include <new>
#include <system_error>
#include <fcntl.h>
#include <pthread.h>
#include <sys/mman.h>
#include <unistd.h>
#include <algorithm>
#include <array>
#include <limits>
#include <type_traits>
#include <fstream>
#include <sstream>
#include <poll.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/syscall.h>

namespace {
constexpr std::uint64_t named_magic = 0x5459434845535043ULL, named_layout = 2;
std::uint64_t monotonic_ns() {
  timespec value{};
  require(clock_gettime(CLOCK_MONOTONIC, &value) == 0, "monotonic clock");
  return value.tv_sec * 1000000000ULL + value.tv_nsec;
}
void posix(int code, const char* operation) {
  if (code != 0) throw std::system_error(code, std::generic_category(), operation);
}
std::uint64_t seal(const Change& e) {
  std::uint64_t result = 1469598103934665603ULL;
  const auto mix = [&](std::uint64_t n) { result = (result ^ n) * 1099511628211ULL; };
  const auto& r = e.record;
  mix(e.sequence); mix(r.epoch); mix(r.version); mix(r.proof);
  mix(r.value_time); mix(r.verified_time); mix(r.received_time);
  mix(r.price); mix(r.quantity); mix(r.checksum); mix(r.gap); mix(r.time_known);
  return result;
}
// Fixed local experiment format. Recovery covers process death, not host failure.
bool journal_io(int fd, Change& event, bool writing, int crash = -1) {
  static_assert(std::is_trivially_copyable_v<Change>);
  auto* bytes = reinterpret_cast<char*>(&event);
  const auto offset = static_cast<off_t>((event.sequence - 1) * sizeof(Change));
  std::size_t done = 0;
  if (writing && crash == 1) {
    require(pwrite(fd, bytes, sizeof(Change) / 2, offset) == sizeof(Change) / 2, "partial fault write");
    _exit(77);
  }
  while (done < sizeof(Change)) {
    const ssize_t n = writing ? pwrite(fd, bytes + done, sizeof(Change) - done, offset + done)
                              : pread(fd, bytes + done, sizeof(Change) - done, offset + done);
    if (n < 0 && errno == EINTR) continue;
    if (n <= 0) return false;
    done += static_cast<std::size_t>(n);
  }
  if (!writing) {
    // Validate the on-disk bool representation before any typed read (UBSan).
    const auto gap = bytes[offsetof(Change, record) + offsetof(Record, gap)];
    const auto known = bytes[offsetof(Change, record) + offsetof(Record, time_known)];
    return (gap == 0 || gap == 1) && (known == 0 || known == 1);
  }
  if (crash == 2) _exit(77);
  int result;
  do { result = fdatasync(fd); } while (result < 0 && errno == EINTR);
  if (result == 0 && crash == 3) _exit(77);
  return result == 0;
}

std::uint64_t process_start(int pid) {
  std::ifstream file("/proc/" + std::to_string(pid) + "/stat");
  std::string line;
  require(static_cast<bool>(std::getline(file, line)), "cannot verify process identity");
  const auto end = line.rfind(')'); // comm can contain spaces and parentheses.
  require(end != std::string::npos, "invalid process stat");
  std::istringstream fields(line.substr(end + 1));
  std::string value;
  for (int field = 3; field <= 22; ++field)
    require(static_cast<bool>(fields >> value), "incomplete process stat");
  return std::stoull(value);
}

// Conservative local exit proof. A timeout or released file lock is not proof.
bool exited(int pid, std::uint64_t start) {
  if (pid == 0) return true; // First publisher, not a takeover.
  const int fd = static_cast<int>(syscall(SYS_pidfd_open, pid, 0));
  if (fd < 0) return errno == ESRCH;
  pollfd p{fd, POLLIN, 0};
  int result;
  do { result = poll(&p, 1, 0); } while (result < 0 && errno == EINTR);
  bool dead = result > 0 && (p.revents & POLLIN);
  if (!dead && result >= 0) {
    try { dead = process_start(pid) != start; } // PID was reused; old instance exited.
    catch (...) { dead = false; } // Unknown identity never authorizes takeover.
  }
  close(fd);
  return dead;
}
}

struct Space::Shared {
  std::uint64_t magic = 0, layout = named_layout, bytes = 0, identity = 0;
  std::uint64_t journal_device = 0, journal_inode = 0, publisher_start = 0;
  int publisher_pid = 0;
  pthread_mutex_t mutex;
  Record record;
  std::uint64_t authoritative_epoch = 1;
  std::uint64_t heartbeat_count = 0;
  bool poisoned = false;
  bool record_failed = false;
  bool ingress_failed = false; // Sticky required-input gap, never repaired here.
  std::uint64_t head = 0;
  std::uint64_t journal_limit = std::numeric_limits<std::uint64_t>::max();
  std::array<Change, Space::buffer_capacity> buffer{};
};

// All cross-process payload accesses are protected by a process-shared mutex.
// Robust-owner recovery invalidates the payload; it never blesses a torn write.
class Space::Guard {
  Shared& shared;
public:
  explicit Guard(Space& space) : shared(*space.shared) {
    const auto began = monotonic_ns();
    timespec deadline{};
    require(clock_gettime(CLOCK_REALTIME, &deadline) == 0, "clock_gettime");
    deadline.tv_sec += 5;
    int code = pthread_mutex_timedlock(&shared.mutex, &deadline);
    const auto elapsed = monotonic_ns() - began;
    space.lock_calls.fetch_add(1, std::memory_order_relaxed);
    space.lock_wait_ns.fetch_add(elapsed, std::memory_order_relaxed);
    auto maximum = space.lock_max_ns.load(std::memory_order_relaxed);
    while (maximum < elapsed && !space.lock_max_ns.compare_exchange_weak(
        maximum, elapsed, std::memory_order_relaxed)) {}
    if (code == EOWNERDEAD) {
      shared.poisoned = true;
      posix(pthread_mutex_consistent(&shared.mutex), "mutex_consistent");
    } else {
      posix(code, "mutex_timedlock");
    }
  }
  ~Guard() { pthread_mutex_unlock(&shared.mutex); }
  Guard(const Guard&) = delete;
  Guard& operator=(const Guard&) = delete;
};

Space::Space(const std::filesystem::path& prototype_journal) {
    const std::string name = "/tyche-freshness-prototype-" + std::to_string(getpid());
    int fd = shm_open(name.c_str(), O_CREAT | O_EXCL | O_RDWR, 0600);
    require(fd >= 0, "shm_open: " + std::string(std::strerror(errno)));
    // Remove only our newly created name. Existing mappings live until unmapped.
    if (shm_unlink(name.c_str()) != 0) {
      close(fd);
      throw std::runtime_error("shm_unlink newly created object");
    }
    if (ftruncate(fd, sizeof(Shared)) != 0) {
      close(fd);
      throw std::runtime_error("ftruncate");
    }
    void* memory = mmap(nullptr, sizeof(Shared), PROT_READ | PROT_WRITE,
                        MAP_SHARED, fd, 0);
    close(fd);
    require(memory != MAP_FAILED, "mmap");
    shared = new (memory) Shared{};
    pthread_mutexattr_t attr;
    posix(pthread_mutexattr_init(&attr), "mutexattr_init");
    posix(pthread_mutexattr_setpshared(&attr, PTHREAD_PROCESS_SHARED), "pshared");
    posix(pthread_mutexattr_setrobust(&attr, PTHREAD_MUTEX_ROBUST), "robust");
    posix(pthread_mutex_init(&shared->mutex, &attr), "mutex_init");
    posix(pthread_mutexattr_destroy(&attr), "mutexattr_destroy");
    shared->record = complete_record(1, 1, 0);
    if (!prototype_journal.empty()) {
      journal = open(prototype_journal.c_str(), O_CREAT | O_EXCL | O_RDWR | O_CLOEXEC, 0600);
      if (journal < 0) {
        pthread_mutex_destroy(&shared->mutex);
        munmap(shared, sizeof(Shared));
        shared = nullptr;
        throw std::runtime_error("create exclusive PROTOTYPE journal: " + std::string(std::strerror(errno)));
      }
    }
  }
Space::~Space() {
    if (journal >= 0) close(journal);
    if (shared) {
      // Independently attached processes can outlive this local object.
      if (!named) pthread_mutex_destroy(&shared->mutex);
      munmap(shared, sizeof(Shared));
    }
    if (region_fd >= 0) close(region_fd);
  }

Space::Space(const Location& location, Access access) : named(true) {
  require(location.identity != 0 && !location.journal.empty(), "named location requires identity and journal");
  require(location.name.starts_with("/tyche-independent-") && location.name.find('/', 1) == std::string::npos,
          "named prototype namespace");
  const bool create = access == Access::create;
  bool created = false;
  try {
    region_fd = shm_open(location.name.c_str(), O_RDWR | (create ? O_CREAT | O_EXCL : 0), 0600);
    if (region_fd < 0) throw std::system_error(errno, std::generic_category(), "open named region");
    created = create;
    // Initialization admission is separate from the publisher's journal lease.
    if (flock(region_fd, (create ? LOCK_EX : LOCK_SH) | LOCK_NB) != 0)
      throw std::system_error(errno, std::generic_category(), "region initialization busy");
    if (create) require(ftruncate(region_fd, sizeof(Shared)) == 0, "size new region");
    struct stat region_stat{};
    require(fstat(region_fd, &region_stat) == 0 && region_stat.st_size == sizeof(Shared),
            "region is uninitialized or layout size is incompatible");
    void* requested = reinterpret_cast<void*>(location.address);
    void* memory = mmap(requested, sizeof(Shared), PROT_READ | PROT_WRITE,
                        MAP_SHARED | (requested ? MAP_FIXED_NOREPLACE : 0), region_fd, 0);
    if (memory == MAP_FAILED) throw std::system_error(errno, std::generic_category(), "map named region");
    if (requested && memory != requested) {
      munmap(memory, sizeof(Shared));
      throw std::runtime_error("kernel did not honor distinct-address mapping");
    }
    shared = static_cast<Shared*>(memory);
    if (create) {
      shared = new (memory) Shared{};
      pthread_mutexattr_t attr;
      posix(pthread_mutexattr_init(&attr), "mutexattr_init");
      posix(pthread_mutexattr_setpshared(&attr, PTHREAD_PROCESS_SHARED), "pshared");
      posix(pthread_mutexattr_setrobust(&attr, PTHREAD_MUTEX_ROBUST), "robust");
      posix(pthread_mutex_init(&shared->mutex, &attr), "mutex_init");
      posix(pthread_mutexattr_destroy(&attr), "mutexattr_destroy");
      journal = open(location.journal.c_str(), O_CREAT | O_EXCL | O_RDWR | O_CLOEXEC, 0600);
      if (journal < 0) throw std::system_error(errno, std::generic_category(), "create named journal");
      struct stat j{};
      require(fstat(journal, &j) == 0, "journal identity");
      shared->identity = location.identity;
      shared->bytes = sizeof(Shared);
      shared->journal_device = j.st_dev;
      shared->journal_inode = j.st_ino;
      shared->authoritative_epoch = 0;
      shared->record = complete_record(0, 0, 0);
      shared->poisoned = true; // Must receive a complete source snapshot.
      shared->magic = named_magic; // Written only after complete initialization.
    } else {
      require(shared->magic == named_magic && shared->layout == named_layout && shared->bytes == sizeof(Shared),
              "incompatible or uninitialized region header");
      require(shared->identity == location.identity, "different region identity");
      journal = open(location.journal.c_str(), (access == Access::publisher ? O_RDWR : O_RDONLY) | O_CLOEXEC);
      if (journal < 0) throw std::system_error(errno, std::generic_category(), "attach named journal");
      struct stat j{};
      require(fstat(journal, &j) == 0 && static_cast<std::uint64_t>(j.st_dev) == shared->journal_device &&
              static_cast<std::uint64_t>(j.st_ino) == shared->journal_inode, "different journal identity");
    }
    require(flock(region_fd, LOCK_UN) == 0, "release initialization lock");
    if (access == Access::publisher) claim_writer();
  } catch (...) {
    if (journal >= 0) close(journal);
    if (shared) munmap(shared, sizeof(Shared));
    if (region_fd >= 0) close(region_fd);
    if (created) shm_unlink(location.name.c_str()); // Only the new object we created.
    throw;
  }
}

void Space::claim_writer() {
  if (flock(journal, LOCK_EX | LOCK_NB) != 0)
    throw std::system_error(errno, std::generic_category(), "publisher still owns journal lease");
  Guard lock(*this);
  require(exited(shared->publisher_pid, shared->publisher_start), "previous publisher exit is not confirmed");
  recover_journal();
  const auto start = process_start(getpid());
  require(shared->authoritative_epoch < std::numeric_limits<std::uint64_t>::max(), "publisher epoch exhausted");
  shared->publisher_start = start;
  shared->publisher_pid = getpid();
  writer_pid = getpid();
  writer_epoch = ++shared->authoritative_epoch;
  // Recovered old events remain ordered; current authority still needs a fresh snapshot.
}

void Space::recover_journal() {
  require(!shared->record_failed, "journal previously failed; recovery needs investigation");
  // Owner death during this scan can retry it; a detected record/I/O error latches closed.
  try {
    struct stat info{};
    require(fstat(journal, &info) == 0 && info.st_size >= 0, "inspect recovery journal");
    require(info.st_size % sizeof(Change) == 0, "incomplete journal tail; evidence retained");
    const auto count = static_cast<std::uint64_t>(info.st_size / sizeof(Change));
    require(count >= shared->head, "journal shorter than published head");
    std::array<Change, buffer_capacity> rebuilt{};
    Change last{};
    for (std::uint64_t sequence = 1; sequence <= count; ++sequence) {
      Change event{};
      event.sequence = sequence;
      require(journal_io(journal, event, false) && event.sequence == sequence &&
              event.seal == seal(event) && event.record.checksum == checksum(event.record) &&
              event.record.epoch > 0 && event.record.epoch <= shared->authoritative_epoch &&
              (!last.sequence || event.record.epoch >= last.record.epoch),
              "invalid recovery journal record; evidence retained");
      rebuilt[(sequence - 1) % buffer_capacity] = event;
      last = event;
    }
    int synced;
    do { synced = fdatasync(journal); } while (synced < 0 && errno == EINTR);
    require(synced == 0, "confirm recovered journal persistence");
    shared->buffer = rebuilt;
    shared->head = count;
    if (count) shared->record = last.record;
    shared->poisoned = count == 0;
    shared->record_failed = false;
  } catch (...) {
    shared->record_failed = true;
    throw;
  }
}

void Space::check_writer() const {
  if (!named) return; // Historical inherited-mapping scenarios retain their seam.
  require(writer_epoch != 0 && writer_epoch == shared->authoritative_epoch &&
          writer_pid == getpid() && shared->publisher_pid == writer_pid,
          "caller does not own current publisher authority");
}

Space::Attachment Space::attachment() {
  Guard lock(*this);
  return {shared->identity, shared->authoritative_epoch, shared->head, shared->publisher_start,
          shared->publisher_pid, reinterpret_cast<std::uintptr_t>(shared)};
}

void Space::unlink_named(const Location& location) {
  // Verify the intended experimental region before removing its name.
  Space verified(location, Access::reader);
  require(shm_unlink(location.name.c_str()) == 0, "unlink verified prototype region");
}
View Space::read(Tick now) {
  Guard lock(*this);
  return current(now);
}
View Space::current(Tick now) const {
  auto& shared = *this->shared;
  View v{shared.record, shared.authoritative_epoch, shared.heartbeat_count,
         shared.poisoned, Validity::valid, now - shared.record.verified_time};
  if (shared.record_failed || v.poisoned || v.record.checksum != checksum(v.record)) v.validity = Validity::damaged;
  else if (v.record.epoch != v.authority) v.validity = Validity::old_epoch;
  else if (v.record.gap || shared.ingress_failed) v.validity = Validity::gap;
  else if (!v.record.time_known || v.age < 0) v.validity = Validity::unknown;
  else if (v.age >= expiry_age) v.validity = Validity::expired;
  else if (v.age >= warning_age) v.validity = Validity::warning;
  return v;
}


void Space::prepare(Tick now) {
  auto writer = serialize_writer();
  Guard lock(*this);
  check_writer();
  draft = complete_record(shared->authoritative_epoch, shared->record.version + 1, now);
  prepared = true;
}
bool Space::publish(Tick now) {
  auto writer = serialize_writer();
  Guard lock(*this);
  check_writer();
  if (!prepared || draft.epoch != shared->authoritative_epoch ||
      (named && shared->record.epoch != shared->authoritative_epoch) ||
      draft.version <= shared->record.version || shared->poisoned || shared->record.gap || shared->record_failed || shared->ingress_failed)
    return false;
  draft.received_time = now;
  if (!append(draft)) return false;
  install(draft);
  prepared = false;
  return true;
}
void Space::replace(Tick now) {
  auto writer = serialize_writer();
  Guard lock(*this);
  check_writer();
  if (shared->ingress_failed) return;
  const auto next = complete_record(shared->authoritative_epoch, shared->record.version + 1, now);
  if (!append(next)) return;
  install(next);
  shared->poisoned = false;
  prepared = false;
}
void Space::verify(Tick now) {
  auto writer = serialize_writer();
  Guard lock(*this);
  check_writer();
  if (shared->ingress_failed) return;
  if (named && shared->record.epoch != shared->authoritative_epoch) return;
  auto r = shared->record;
  ++r.proof;
  r.verified_time = r.received_time = now;
  if (append(r)) install(r);
}
void Space::replay(Tick now) {
  auto writer = serialize_writer();
  Guard lock(*this);
  check_writer();
  shared->record.received_time = now;
}
void Space::heartbeat() {
  Guard lock(*this);
  check_writer();
  ++shared->heartbeat_count;
}
void Space::restart() {
  Guard lock(*this);
  require(!named, "named publisher changes only after independently verified exit");
  ++shared->authoritative_epoch;
  prepared = false;
}

std::unique_lock<std::mutex> Space::serialize_writer() {
  if (!named) return {}; // A local mutex cannot serialize inherited processes.
  // Reject an inherited writer before touching a possibly inherited locked mutex.
  require(writer_pid == getpid() && writer_epoch != 0, "named writer belongs to another process");
  return std::unique_lock<std::mutex>(writer_mutex);
}
Space::LockMetrics Space::lock_metrics() const {
  return {lock_calls.load(), lock_wait_ns.load(), lock_max_ns.load()};
}
Change Space::proposal(std::uint64_t sequence, const Record& record) {
  Change result{sequence, record, 0};
  result.seal = seal(result);
  return result;
}
Change Space::batch_seed() {
  auto writer = serialize_writer();
  Guard lock(*this);
  check_writer();
  require(named && journal >= 0 && !shared->record_failed && !shared->ingress_failed &&
          !shared->poisoned && !shared->record.gap && shared->record.epoch == writer_epoch,
          "batch requires healthy initialized named publisher");
  return proposal(shared->head, shared->record);
}
void Space::restrict_ingress() {
  // The admission/control path never takes the disk writer's mutex.
  Guard lock(*this);
  check_writer();
  shared->ingress_failed = true;
}

Space::BatchResult Space::publish_admitted_batch(const std::vector<Change>& events) {
  auto writer = serialize_writer(); // Fixed order: named writer, then shared Guard.
  BatchResult result;
  result.count = events.size();
  require(!events.empty() && events.size() <= buffer_capacity, "bounded nonempty batch");
  std::uint64_t old_head = 0;
  {
    Guard lock(*this);
    check_writer();
    if (shared->poisoned || shared->record_failed || shared->record.gap ||
        shared->record.epoch != writer_epoch) return result;
    old_head = shared->head;
    for (std::size_t i = 0; i < events.size(); ++i) {
      const auto& e = events[i];
      if (e.sequence != old_head + i + 1 || e.record.version != shared->record.version + i + 1 ||
          e.record.epoch != writer_epoch || e.seal != seal(e) ||
          e.record.checksum != checksum(e.record) || e.record.gap || !e.record.time_known ||
          e.sequence > shared->journal_limit) return result;
    }
  }
  // The journal lease plus local named-writer serialization reserves these exact
  // slots. Readers still see old_head while these complete proposed bytes land.
  result.write_started_ns = monotonic_ns();
  bool intact = true;
  if (batch_crash_point == 0) _exit(77);
  for (std::size_t i = 0; i < events.size() && intact; ++i) {
    const auto& event = events[i];
    const auto* bytes = reinterpret_cast<const char*>(&event);
    const auto offset = static_cast<off_t>((event.sequence - 1) * sizeof(Change));
    if (batch_crash_point == 2 && i == 1) {
      require(pwrite(journal, bytes, sizeof(Change) / 2, offset) == sizeof(Change) / 2, "half batch tail fault");
      _exit(77);
    }
    std::size_t done = 0;
    while (done < sizeof(Change)) {
      const auto n = pwrite(journal, bytes + done, sizeof(Change) - done, offset + done);
      if (n < 0 && errno == EINTR) continue;
      if (n <= 0) { intact = false; break; }
      done += static_cast<std::size_t>(n);
    }
    if (batch_crash_point == 1 && i == 0) _exit(77);
  }
  if (batch_crash_point == 3) _exit(77); // Full batch, sync not yet observed.
  if (batch_gate_notify >= 0) {
    const char ready = 'S'; char release = 0;
    require(write(batch_gate_notify, &ready, 1) == 1, "batch gate signal");
    ssize_t received;
    do { received = ::read(batch_gate_release, &release, 1); } while (received < 0 && errno == EINTR);
    require(received == 1 && release == 'G', "batch gate release");
    batch_gate_notify = batch_gate_release = -1; // One deterministic gate only.
  }
  result.sync_started_ns = monotonic_ns();
  int synced = -1;
  if (intact && !batch_fail_sync)
    do { synced = fdatasync(journal); } while (synced < 0 && errno == EINTR);
  if (!intact || synced != 0) {
    Guard lock(*this);
    shared->record_failed = true;
    result.state = BatchState::unknown; // Full/partial bytes retained, never retried here.
    result.returned_ns = monotonic_ns();
    return result;
  }
  result.synced_ns = monotonic_ns();
  if (batch_crash_point == 4) _exit(77); // Saved, not yet shared-published.
  {
    Guard lock(*this);
    check_writer();
    require(shared->head == old_head, "serialized batch head changed");
    if (shared->record_failed || shared->poisoned) {
      result.state = BatchState::unknown;
      result.returned_ns = monotonic_ns();
      return result;
    }
    for (const auto& event : events)
      shared->buffer[(event.sequence - 1) % buffer_capacity] = event;
    shared->head = events.back().sequence;
    if (batch_crash_point == 5) { shared->record.price = events.back().record.price; _exit(77); }
    shared->record = events.back().record;
    prepared = false;
    result.published_ns = monotonic_ns();
  }
  if (batch_crash_point == 6) _exit(77); // Shared publication, caller has no reply.
  result.state = BatchState::committed;
  result.returned_ns = monotonic_ns();
  return result;
}
void experiment::Faults::reset(Space& space, Tick now) {
  require(space.journal < 0, "cannot reset an ordered journal in place");
  Space::Guard lock(space);
  space.shared->authoritative_epoch = 1;
  space.shared->heartbeat_count = 0;
  space.shared->poisoned = false;
  space.shared->record = complete_record(1, 1, now);
  space.prepared = false;
}
void experiment::Faults::gap(Space& space) {
  Space::Guard lock(space);
  space.shared->record.gap = true;
}
void experiment::Faults::unknown_time(Space& space) {
  Space::Guard lock(space);
  space.shared->record.time_known = false;
}
void experiment::Faults::crash(Space& space) {
  Space::Guard lock(space);
  space.shared->record.price = 999999;
  _exit(77);
}

bool Space::append(const Record& record) {
  if (shared->record_failed) return false;
  if (journal < 0) return true; // Preserve the existing snapshot-only experiment.
  Change event{shared->head + 1, record, 0};
  event.seal = seal(event);
  if (crash_point == 0) _exit(77);
  if (event.sequence > shared->journal_limit || !journal_io(journal, event, true, crash_point)) {
    shared->record_failed = true;
    return false; // Never advertise an event whose complete record was not saved.
  }
  shared->buffer[(event.sequence - 1) % buffer_capacity] = event;
  if (crash_point == 4) _exit(77);
  shared->head = event.sequence;
  if (crash_point == 5) _exit(77);
  return true;
}

void Space::install(const Record& record) {
  if (crash_point == 6) {
    shared->record.price = record.price;
    _exit(77);
  }
  shared->record = record;
  if (crash_point == 7) _exit(77);
}

void experiment::Faults::publication_crash(Space& space, int point) {
  require(point >= 0 && point <= 7, "unknown publication crash point");
  space.crash_point = point;
}
void experiment::Faults::batch_crash(Space& space, int point) {
  require(point >= 0 && point <= 6, "unknown batch crash point");
  space.batch_crash_point = point;
}
void experiment::Faults::batch_sync_failure(Space& space) { space.batch_fail_sync = true; }
void experiment::Faults::batch_gate(Space& space, int notify_fd, int release_fd) {
  space.batch_gate_notify = notify_fd;
  space.batch_gate_release = release_fd;
}

Changes Space::read_after(std::uint64_t cursor, std::size_t budget, Tick now) {
  require(journal >= 0, "ordered reading requires a PROTOTYPE journal");
  // One lock covers latest snapshot, high-water mark and selected events.
  Guard lock(*this);
  Changes result{current(now), shared->head, {}, 0, true};
  if (shared->record_failed || shared->poisoned || cursor > shared->head) {
    result.complete = false;
    return result;
  }
  const auto count = std::min<std::uint64_t>(std::min(budget, buffer_capacity), shared->head - cursor);
  for (std::uint64_t i = 1; i <= count; ++i) {
    const auto next = cursor + i;
    Change event{};
    event.sequence = next;
    bool intact = true;
    if (shared->head - next >= buffer_capacity) {
      intact = journal_io(journal, event, false);
      ++result.from_journal;
    } else event = shared->buffer[(next - 1) % buffer_capacity];
    if (!intact || event.sequence != next || event.seal != seal(event) ||
        event.record.checksum != checksum(event.record)) {
      shared->record_failed = true;
      result.latest.validity = Validity::damaged;
      result.complete = false;
      result.events.clear(); // A failed batch advances no cursor.
      return result;
    }
    result.events.push_back(event);
  }
  return result;
}
void experiment::Faults::truncate_journal(Space& space, std::uint64_t remaining_records) {
  Space::Guard lock(space);
  require(space.journal >= 0, "journal required");
  require(ftruncate(space.journal, static_cast<off_t>(remaining_records * sizeof(Change))) == 0,
          "truncate own PROTOTYPE journal");
}
void experiment::Faults::limit_journal(Space& space, std::uint64_t maximum_records) {
  Space::Guard lock(space);
  space.shared->journal_limit = maximum_records;
}
