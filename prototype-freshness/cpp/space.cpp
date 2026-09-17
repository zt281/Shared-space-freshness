#include "space.hpp"
#include "faults.hpp"
#include <cerrno>
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

namespace {
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
// Fixed local experiment format; not portable serialization or crash recovery.
bool journal_io(int fd, Change& event, bool writing) {
  static_assert(std::is_trivially_copyable_v<Change>);
  auto* bytes = reinterpret_cast<char*>(&event);
  const auto offset = static_cast<off_t>((event.sequence - 1) * sizeof(Change));
  std::size_t done = 0;
  while (done < sizeof(Change)) {
    const ssize_t n = writing ? pwrite(fd, bytes + done, sizeof(Change) - done, offset + done)
                              : pread(fd, bytes + done, sizeof(Change) - done, offset + done);
    if (n < 0 && errno == EINTR) continue;
    if (n <= 0) return false;
    done += static_cast<std::size_t>(n);
  }
  if (!writing) return true;
  int result;
  do { result = fdatasync(fd); } while (result < 0 && errno == EINTR);
  return result == 0;
}
}

struct Space::Shared {
  pthread_mutex_t mutex;
  Record record;
  std::uint64_t authoritative_epoch = 1;
  std::uint64_t heartbeat_count = 0;
  bool poisoned = false;
  bool record_failed = false;
  std::uint64_t head = 0;
  std::uint64_t journal_limit = std::numeric_limits<std::uint64_t>::max();
  std::array<Change, Space::buffer_capacity> buffer{};
};

// All cross-process payload accesses are protected by a process-shared mutex.
// Robust-owner recovery invalidates the payload; it never blesses a torn write.
class Space::Guard {
  Shared& shared;
public:
  explicit Guard(Shared& s) : shared(s) {
    timespec deadline{};
    require(clock_gettime(CLOCK_REALTIME, &deadline) == 0, "clock_gettime");
    deadline.tv_sec += 5;
    int code = pthread_mutex_timedlock(&shared.mutex, &deadline);
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
      pthread_mutex_destroy(&shared->mutex);
      munmap(shared, sizeof(Shared));
    }
  }
View Space::read(Tick now) {
  Guard lock(*shared);
  return current(now);
}
View Space::current(Tick now) const {
  auto& shared = *this->shared;
  View v{shared.record, shared.authoritative_epoch, shared.heartbeat_count,
         shared.poisoned, Validity::valid, now - shared.record.verified_time};
  if (shared.record_failed || v.poisoned || v.record.checksum != checksum(v.record)) v.validity = Validity::damaged;
  else if (v.record.epoch != v.authority) v.validity = Validity::old_epoch;
  else if (v.record.gap) v.validity = Validity::gap;
  else if (!v.record.time_known || v.age < 0) v.validity = Validity::unknown;
  else if (v.age >= expiry_age) v.validity = Validity::expired;
  else if (v.age >= warning_age) v.validity = Validity::warning;
  return v;
}


void Space::prepare(Tick now) {
  Guard lock(*shared);
  draft = complete_record(shared->authoritative_epoch, shared->record.version + 1, now);
  prepared = true;
}
bool Space::publish(Tick now) {
  Guard lock(*shared);
  if (!prepared || draft.epoch != shared->authoritative_epoch ||
      draft.version <= shared->record.version || shared->poisoned || shared->record.gap || shared->record_failed)
    return false;
  draft.received_time = now;
  if (!append(draft)) return false;
  shared->record = draft;
  prepared = false;
  return true;
}
void Space::replace(Tick now) {
  Guard lock(*shared);
  const auto next = complete_record(shared->authoritative_epoch, shared->record.version + 1, now);
  if (!append(next)) return;
  shared->record = next;
  shared->poisoned = false;
  prepared = false;
}
void Space::verify(Tick now) {
  Guard lock(*shared);
  auto r = shared->record;
  ++r.proof;
  r.verified_time = r.received_time = now;
  if (append(r)) shared->record = r;
}
void Space::replay(Tick now) {
  Guard lock(*shared);
  shared->record.received_time = now;
}
void Space::heartbeat() {
  Guard lock(*shared);
  ++shared->heartbeat_count;
}
void Space::restart() {
  Guard lock(*shared);
  ++shared->authoritative_epoch;
  prepared = false;
}
void experiment::Faults::reset(Space& space, Tick now) {
  require(space.journal < 0, "cannot reset an ordered journal in place");
  Space::Guard lock(*space.shared);
  space.shared->authoritative_epoch = 1;
  space.shared->heartbeat_count = 0;
  space.shared->poisoned = false;
  space.shared->record = complete_record(1, 1, now);
  space.prepared = false;
}
void experiment::Faults::gap(Space& space) {
  Space::Guard lock(*space.shared);
  space.shared->record.gap = true;
}
void experiment::Faults::unknown_time(Space& space) {
  Space::Guard lock(*space.shared);
  space.shared->record.time_known = false;
}
void experiment::Faults::crash(Space& space) {
  Space::Guard lock(*space.shared);
  space.shared->record.price = 999999;
  _exit(77);
}

bool Space::append(const Record& record) {
  if (shared->record_failed) return false;
  if (journal < 0) return true; // Preserve the existing snapshot-only experiment.
  Change event{shared->head + 1, record, 0};
  event.seal = seal(event);
  if (event.sequence > shared->journal_limit || !journal_io(journal, event, true)) {
    shared->record_failed = true;
    return false; // Never advertise an event whose complete record was not saved.
  }
  shared->buffer[(event.sequence - 1) % buffer_capacity] = event;
  shared->head = event.sequence;
  return true;
}

Changes Space::read_after(std::uint64_t cursor, std::size_t budget, Tick now) {
  require(journal >= 0, "ordered reading requires a PROTOTYPE journal");
  // One lock covers latest snapshot, high-water mark and selected events.
  Guard lock(*shared);
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
  Space::Guard lock(*space.shared);
  require(space.journal >= 0, "journal required");
  require(ftruncate(space.journal, static_cast<off_t>(remaining_records * sizeof(Change))) == 0,
          "truncate own PROTOTYPE journal");
}
void experiment::Faults::limit_journal(Space& space, std::uint64_t maximum_records) {
  Space::Guard lock(*space.shared);
  space.shared->journal_limit = maximum_records;
}
