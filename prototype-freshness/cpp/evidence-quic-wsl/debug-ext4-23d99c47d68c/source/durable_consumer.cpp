#include "durable_consumer.hpp"
#include "faults.hpp"
#include <array>
#include <cerrno>
#include <system_error>
#include <fcntl.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <unistd.h>

namespace {
constexpr std::array<const char*, 7> outcomes{
  "none", "pending", "unknown", "expired", "old_epoch", "not_ready", "abandoned_restart"};
std::uint64_t outcome_code(const std::string& outcome) {
  for (std::size_t i = 0; i < outcomes.size(); ++i) if (outcome == outcomes[i]) return i;
  throw std::runtime_error("unsupported saved intent outcome");
}
std::uint64_t seal(const DurableConsumer::State& s) {
  std::uint64_t hash = 1469598103934665603ULL;
  for (auto value : {s.magic, s.layout, s.space, s.consumer, s.revision, s.cursor,
                    s.processed, s.last_event_seal, s.quantity_sum, s.price_sum, s.chain,
                    s.stopped, s.intent_epoch, static_cast<std::uint64_t>(s.intent_expires), s.intent_outcome})
    hash = (hash ^ value) * 1099511628211ULL;
  return hash;
}
struct File {
  int fd;
  explicit File(int value) : fd(value) { require(fd >= 0, "open checkpoint file"); }
  ~File() { close(fd); }
};
void transfer(int fd, void* buffer, std::size_t size, bool writing) {
  auto* bytes = static_cast<char*>(buffer);
  std::size_t done = 0;
  while (done < size) {
    const auto n = writing ? write(fd, bytes + done, size - done) : read(fd, bytes + done, size - done);
    if (n < 0 && errno == EINTR) continue;
    require(n > 0, "incomplete checkpoint I/O");
    done += static_cast<std::size_t>(n);
  }
}
void sync_file(int fd, bool metadata = false) {
  int result;
  do { result = metadata ? fsync(fd) : fdatasync(fd); } while (result < 0 && errno == EINTR);
  require(result == 0, "checkpoint sync failed");
}
}

DurableConsumer::DurableConsumer(ReadableSpace& input, const std::filesystem::path& checkpoint,
                                 std::uint64_t identity, bool create)
    : space(input), ordered(input, 4, false), path(checkpoint) {
  require(identity != 0 && path.filename().string().starts_with("PROTOTYPE-"), "explicit PROTOTYPE checkpoint required");
  try {
    lease = open((path.string() + ".lock").c_str(), O_RDWR | O_CREAT | O_CLOEXEC, 0600);
    require(lease >= 0 && flock(lease, LOCK_EX | LOCK_NB) == 0, "consumer checkpoint already owned");
    directory = open(path.parent_path().c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    require(directory >= 0, "open checkpoint directory");
    if (create) {
      require(!std::filesystem::exists(path), "checkpoint already exists; cannot initialize over progress");
      state.space = space.attachment().identity;
      state.consumer = identity;
      save(state, true);
    } else {
      File file(open(path.c_str(), O_RDONLY | O_CLOEXEC));
      struct stat info{};
      require(fstat(file.fd, &info) == 0 && info.st_size == sizeof(State), "incompatible checkpoint length");
      transfer(file.fd, &state, sizeof(state), false);
      require(state.magic == State{}.magic && state.layout == 1 && state.seal == seal(state) &&
              state.intent_outcome < outcomes.size() && state.stopped <= 1 && state.processed == state.cursor,
              "invalid checkpoint; evidence retained");
      require(state.space == space.attachment().identity && state.consumer == identity,
              "checkpoint identity mismatch");
      require(state.cursor <= space.attachment().head, "checkpoint ahead of published history");
      if (state.cursor) {
        const auto last = space.read_after(state.cursor - 1, 1, 0);
        require(last.complete && last.events.size() == 1 && last.events[0].seal == state.last_event_seal,
                "checkpoint history does not match");
      }
      ordered.cursor = state.cursor;
      ordered.processed = state.processed;
      ordered.policy.restore_control({state.stopped != 0, state.intent_epoch, state.intent_expires,
                                      outcomes[state.intent_outcome]});
      // A saved pending intent is retired, never replayed after restart.
      if (state.intent_outcome == 1) persist_control();
    }
  } catch (...) {
    if (directory >= 0) close(directory);
    if (lease >= 0) close(lease);
    throw;
  }
}
DurableConsumer::~DurableConsumer() {
  if (directory >= 0) close(directory);
  if (lease >= 0) close(lease);
}
void DurableConsumer::trigger(int point) const { if (crash_point == point) _exit(77); }
void DurableConsumer::save(State next, bool create) {
  static_assert(sizeof(State) == 16 * sizeof(std::uint64_t));
  next.revision = state.revision + 1;
  next.seal = seal(next);
  const auto temporary = path.string() + ".pending-" + std::to_string(getpid()) + "-" + std::to_string(next.revision);
  File file(open(temporary.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600));
  if (crash_point == 1) {
    transfer(file.fd, &next, sizeof(next) / 2, true);
    _exit(77);
  }
  transfer(file.fd, &next, sizeof(next), true);
  trigger(2);
  sync_file(file.fd);
  trigger(3);
  if (create) {
    require(link(temporary.c_str(), path.c_str()) == 0, "exclusive checkpoint creation");
    require(unlink(temporary.c_str()) == 0, "unlink own checkpoint staging name");
  } else if (rename(temporary.c_str(), path.c_str()) != 0) {
    const int error = errno; // Capture before formatting or any other system call.
    throw std::system_error(error, std::generic_category(),
                            "replace complete checkpoint errno=" + std::to_string(error));
  }
  trigger(4);
  sync_file(directory, true);
  trigger(5);
  state = next;
}
void DurableConsumer::persist_control() {
  auto next = state;
  const auto control = ordered.policy.saved_control();
  next.stopped = control.stopped;
  next.intent_epoch = control.epoch;
  next.intent_expires = control.expires;
  next.intent_outcome = outcome_code(control.outcome);
  try { save(next); }
  catch (const std::exception& error) { failed = true; failure = error.what(); throw; }
}
OrderedConsumer::Status DurableConsumer::status(Tick now) {
  auto result = ordered.status(now);
  if (failed) { result.allowed = false; result.complete = false; result.recovering = true; }
  return result;
}
bool DurableConsumer::consume(Tick now, std::size_t budget, std::vector<Change>& processed) {
  if (failed) return false;
  return ordered.consume(now, budget, [&](const Change& event) {
    auto next = state;
    require(event.sequence == next.cursor + 1, "checkpoint progress must follow every event");
    next.cursor = event.sequence;
    ++next.processed;
    next.last_event_seal = event.seal;
    next.quantity_sum += event.record.quantity;
    next.price_sum += event.record.price;
    next.chain = (next.chain ^ event.seal) * 1099511628211ULL;
    trigger(0); // Pure work finished; no committed result and no external effects yet.
    try { save(next); }
    catch (const std::exception& error) { failed = true; failure = error.what(); return false; }
    trigger(6); // Committed result, OrderedConsumer has not advanced its memory cursor.
    processed.push_back(event);
    return true;
  });
}
void DurableConsumer::stop() { ordered.stop(); persist_control(); }
void DurableConsumer::resume() { require(!failed, "checkpoint failed"); ordered.resume(); persist_control(); }
bool DurableConsumer::issue(Tick now) {
  if (failed || !ordered.issue(now)) return false;
  persist_control();
  return true;
}
std::string DurableConsumer::execute(Tick now) {
  if (failed) return "not_ready";
  const auto result = ordered.execute(now);
  persist_control(); // Record the possible attempt before the mock external side effect.
  if (result == "unknown") {
    trigger(7);
    File external(open((path.string() + ".simulated-submissions.jsonl").c_str(),
                       O_WRONLY | O_APPEND | O_CREAT | O_CLOEXEC, 0600));
    auto record = std::string("{\"checkpoint_revision\":") + std::to_string(state.revision) +
                  ",\"intent_epoch\":" + std::to_string(state.intent_epoch) + ",\"simulated\":true}\n";
    transfer(external.fd, record.data(), record.size(), true);
    sync_file(external.fd);
    trigger(8);
  }
  return result;
}
void experiment::Faults::checkpoint_crash(DurableConsumer& consumer, int point) {
  require(point >= 0 && point <= 8, "unknown checkpoint crash point");
  consumer.crash_point = point;
}
