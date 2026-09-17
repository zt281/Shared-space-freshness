// Disposable Linux prototype. Logical time is injected; no trading connection.
#include <cerrno>
#include <csignal>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <new>
#include <stdexcept>
#include <string>
#include <system_error>
#include <thread>
#include <chrono>
#include <fcntl.h>
#include <pthread.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include <unistd.h>

using Tick = std::int64_t;
constexpr Tick warning_age = 700, expiry_age = 1000;
constexpr Tick stable_period = 200, command_lifetime = 500;
constexpr std::uint64_t checksum_salt = 0xCAFE1234ULL;

void require(bool condition, const std::string& message) {
  if (!condition) throw std::runtime_error(message);
}
void posix(int code, const char* operation) {
  if (code != 0) throw std::system_error(code, std::generic_category(), operation);
}

struct Record {
  std::uint64_t epoch = 1, version = 1, proof = 1;
  Tick value_time = 0, verified_time = 0, received_time = 0;
  std::uint64_t price = 100, quantity = 1, checksum = 0;
  bool gap = false, time_known = true;
};
std::uint64_t checksum(const Record& r) {
  return r.price ^ (r.quantity << 16) ^ r.version ^ checksum_salt;
}
Record complete_record(std::uint64_t epoch, std::uint64_t version, Tick now) {
  Record r;
  r.epoch = epoch;
  r.version = r.proof = version;
  r.value_time = r.verified_time = r.received_time = now;
  r.price = 100 + version;
  r.quantity = version;
  r.checksum = checksum(r);
  return r;
}
struct Shared {
  pthread_mutex_t mutex;
  Record record;
  std::uint64_t authoritative_epoch = 1;
  std::uint64_t heartbeat_count = 0;
  bool poisoned = false;
};

// All cross-process payload accesses are protected by a process-shared mutex.
// Robust-owner recovery invalidates the payload; it never blesses a torn write.
class Guard {
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

class Space {
  Shared* shared = nullptr;
public:
  Space() {
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
  }
  ~Space() {
    if (shared) {
      pthread_mutex_destroy(&shared->mutex);
      munmap(shared, sizeof(Shared));
    }
  }
  Shared& get() { return *shared; }
};

enum class Validity { valid, warning, expired, unknown, gap, old_epoch, damaged };
const char* label(Validity v) {
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
View read_view(Shared& shared, Tick now) {
  Guard lock(shared);
  View v{shared.record, shared.authoritative_epoch, shared.heartbeat_count,
         shared.poisoned, Validity::valid, now - shared.record.verified_time};
  if (v.poisoned || v.record.checksum != checksum(v.record)) v.validity = Validity::damaged;
  else if (v.record.epoch != v.authority) v.validity = Validity::old_epoch;
  else if (v.record.gap) v.validity = Validity::gap;
  else if (!v.record.time_known || v.age < 0) v.validity = Validity::unknown;
  else if (v.age >= expiry_age) v.validity = Validity::expired;
  else if (v.age >= warning_age) v.validity = Validity::warning;
  return v;
}

enum class Op { reset, draft, publish, replay, heartbeat, verify, gap,
                unknown_time, snapshot, restart_epoch, stress, crash, quit };
struct Message { Op op; Tick now; std::uint64_t count = 0; };
void transfer(int fd, void* data, std::size_t size, bool writing) {
  auto* p = static_cast<char*>(data);
  while (size) {
    ssize_t n = writing ? write(fd, p, size) : read(fd, p, size);
    if (n < 0 && errno == EINTR) continue;
    require(n > 0, "prototype control pipe closed or failed");
    size -= static_cast<std::size_t>(n);
    p += n;
  }
}
void write_event(std::ostream& out, const char* event, Tick now, const View& v) {
  out << "{\"event\":\"" << event << "\",\"pid\":" << getpid()
      << ",\"logical_ms\":" << now << ",\"epoch\":" << v.record.epoch
      << ",\"authority\":" << v.authority << ",\"version\":" << v.record.version
      << ",\"proof\":" << v.record.proof << ",\"value_ms\":" << v.record.value_time
      << ",\"verified_ms\":" << v.record.verified_time
      << ",\"received_ms\":" << v.record.received_time << ",\"age_ms\":" << v.age
      << ",\"price\":" << v.record.price << ",\"quantity\":" << v.record.quantity
      << ",\"checksum\":" << v.record.checksum
      << ",\"checksum_ok\":" << (v.record.checksum == checksum(v.record) ? "true" : "false")
      << ",\"heartbeats\":" << v.heartbeats
      << ",\"poisoned\":" << (v.poisoned ? "true" : "false")
      << ",\"gap\":" << (v.record.gap ? "true" : "false")
      << ",\"time_known\":" << (v.record.time_known ? "true" : "false")
      << ",\"validity\":\"" << label(v.validity) << "\"}\n";
}

class Publisher {
  Shared& shared;
  std::filesystem::path evidence;
  pid_t pid = -1;
  int request = -1, response = -1;
  void worker(int in, int out) {
    std::ofstream log(evidence / "publisher.jsonl", std::ios::app);
    require(log.good(), "publisher evidence file");
    Record draft = complete_record(1, 2, 0);
    for (;;) {
      Message m{};
      transfer(in, &m, sizeof(m), false);
      if (m.op == Op::quit) return;
      if (m.op == Op::crash) {
        Guard lock(shared);
        shared.record.price = 999999; // Intentionally torn payload under owned lock.
        _exit(77); // A real process exits without unlocking.
      }
      if (m.op == Op::stress) {
        for (std::uint64_t i = 0; i < m.count; ++i) {
          {
            Guard lock(shared);
            shared.record = complete_record(shared.authoritative_epoch,
                                             shared.record.version + 1, m.now);
          }
          write_event(log, "complete_publish", m.now, read_view(shared, m.now));
          if (i % 100 == 0) std::this_thread::sleep_for(std::chrono::microseconds(100));
        }
      } else {
        Guard lock(shared);
        auto& r = shared.record;
        switch (m.op) {
          case Op::reset:
            shared.authoritative_epoch = 1;
            shared.heartbeat_count = 0;
            shared.poisoned = false;
            r = complete_record(1, 1, m.now);
            break;
          case Op::draft: draft = complete_record(shared.authoritative_epoch, r.version + 1, m.now); break;
          case Op::publish: r = draft; r.received_time = m.now; break;
          case Op::replay: r.received_time = m.now; break;
          case Op::heartbeat: ++shared.heartbeat_count; break;
          case Op::verify: ++r.proof; r.verified_time = r.received_time = m.now; break;
          case Op::gap: r.gap = true; break;
          case Op::unknown_time: r.time_known = false; break;
          case Op::snapshot:
            r = complete_record(shared.authoritative_epoch, r.version + 1, m.now);
            shared.poisoned = false;
            break;
          case Op::restart_epoch: ++shared.authoritative_epoch; break;
          default: break;
        }
      }
      write_event(log, "publisher_action", m.now, read_view(shared, m.now));
      log.flush();
      require(log.good(), "publisher evidence write failed");
      int ack = 1;
      transfer(out, &ack, sizeof(ack), true);
    }
  }
public:
  Publisher(Shared& s, std::filesystem::path path) : shared(s), evidence(std::move(path)) { start(); }
  void start() {
    int requests[2], responses[2];
    require(pipe(requests) == 0, "request pipe");
    require(pipe(responses) == 0, "response pipe");
    pid = fork();
    require(pid >= 0, "fork publisher");
    if (pid == 0) {
      close(requests[1]); close(responses[0]);
      try { worker(requests[0], responses[1]); _exit(0); }
      catch (const std::exception& e) { std::cerr << e.what() << '\n'; _exit(2); }
    }
    close(requests[0]); close(responses[1]);
    request = requests[1]; response = responses[0];
  }
  pid_t process_id() const { return pid; }
  void begin(Op op, Tick now, std::uint64_t count = 0) {
    Message m{op, now, count}; transfer(request, &m, sizeof(m), true);
  }
  void finish() { int ack = 0; transfer(response, &ack, sizeof(ack), false); require(ack == 1, "publisher ack"); }
  void send(Op op, Tick now) { begin(op, now); finish(); }
  void crash() {
    begin(Op::crash, 0);
    int status = 0;
    require(waitpid(pid, &status, 0) == pid, "waitpid crash");
    pid = -1;
    close(request); close(response); request = response = -1;
    require(WIFEXITED(status) && WEXITSTATUS(status) == 77, "writer did not crash as intended");
  }
  ~Publisher() {
    if (pid > 0) {
      // Reap only our child. A failed scenario must not leave a worker behind.
      kill(pid, SIGTERM);
      int status = 0; waitpid(pid, &status, 0);
    }
    if (request >= 0) close(request);
    if (response >= 0) close(response);
  }
  void stop() {
    begin(Op::quit, 0);
    int status = 0;
    require(waitpid(pid, &status, 0) == pid, "waitpid publisher");
    pid = -1;
    require(WIFEXITED(status) && WEXITSTATUS(status) == 0, "publisher failure");
  }
};

// Consumer uses only the shared-space view, not its mutex or transport state.
struct Consumer {
  bool reconciled = true, stopped = false;
  Tick ready_at = 0;
  std::uint64_t epoch = 1;
  struct Intent { std::uint64_t epoch; Tick expires; std::string result; };
  Intent intent{0, 0, "none"};
  void observe(const View& v, Tick now) {
    if (!v.usable() || v.authority != epoch) {
      reconciled = false; ready_at = -1; epoch = v.authority;
    }
    if (v.usable() && ready_at < 0) ready_at = now + stable_period;
  }
  bool allowed(const View& v, Tick now) const {
    return v.usable() && reconciled && !stopped && ready_at >= 0 && now >= ready_at;
  }
  bool issue(const View& v, Tick now) {
    if (!allowed(v, now) || intent.result == "pending" || intent.result == "unknown") return false;
    intent = {v.authority, now + command_lifetime, "pending"}; return true;
  }
  std::string execute(const View& v, Tick now) {
    if (intent.result != "pending") return "no_resubmit";
    if (now >= intent.expires) return intent.result = "expired";
    if (intent.epoch != v.authority) return intent.result = "old_epoch";
    if (!allowed(v, now)) return intent.result = "not_ready";
    return intent.result = "unknown"; // Simulated call; no broker or exchange.
  }
};

int run(const std::filesystem::path& output) {
  require(!std::filesystem::exists(output), "evidence directory already exists; choose a new path");
  std::filesystem::create_directories(output);
  Space space;
  Publisher writer(space.get(), output);
  std::ofstream trace(output / "consumer.jsonl"), results(output / "results.jsonl");
  require(trace.good() && results.good(), "consumer evidence files");
  Consumer consumer;
  Tick now = 0;
  int checks = 0;
  auto observe = [&](const char* event) {
    auto v = read_view(space.get(), now);
    consumer.observe(v, now);
    write_event(trace, event, now, v);
    return v;
  };
  auto check = [&](const char* name, bool pass) {
    ++checks;
    results << "{\"check\":\"" << name << "\",\"passed\":" << (pass ? "true" : "false") << "}\n";
    results.flush();
    require(pass, std::string("scenario failed: ") + name);
    std::cout << "PASS " << name << '\n';
  };
  auto reset = [&]() { now = 0; writer.send(Op::reset, now); consumer = Consumer{}; };

  check("separate_processes", writer.process_id() != getpid());
  auto v = observe("initial");
  check("initial_usable", consumer.allowed(v, now));
  writer.send(Op::draft, 100);
  now = 100; v = observe("unpublished_draft");
  check("draft_not_visible", v.record.version == 1 && v.record.value_time == 0);
  writer.send(Op::publish, now); v = observe("complete_publish");
  check("complete_version_visible", v.record.version == 2 && v.record.checksum == checksum(v.record));

  reset(); now = warning_age; v = observe("warning_boundary");
  check("warning_still_usable", v.validity == Validity::warning && consumer.allowed(v, now));
  now = expiry_age; v = observe("expiry_boundary");
  check("expiry_blocks_new_intent", !consumer.issue(v, now) && v.validity == Validity::expired);
  writer.send(Op::replay, now); writer.send(Op::heartbeat, now); v = observe("old_copy_and_heartbeat");
  check("replay_and_heartbeat_do_not_renew", v.record.received_time == now && v.record.verified_time == 0 && !v.usable());
  writer.send(Op::verify, now); v = observe("source_business_verification");
  check("business_proof_renews_without_price_change", v.usable() && v.record.version == 1 && v.record.proof == 2 && !consumer.allowed(v, now));
  consumer.reconciled = true;
  now += stable_period; v = observe("reconciled_and_stable");
  check("recovery_requires_stable_period", consumer.allowed(v, now));

  reset(); consumer.stopped = true;
  writer.send(Op::gap, now); observe("gap");
  writer.send(Op::verify, now); v = observe("proof_does_not_repair_gap");
  check("gap_requires_snapshot", v.validity == Validity::gap);
  writer.send(Op::snapshot, now); observe("full_snapshot");
  consumer.reconciled = true; now = stable_period; v = observe("recovery_with_manual_stop");
  check("manual_stop_survives_recovery", !consumer.allowed(v, now));
  consumer.stopped = false;
  check("explicit_resume", consumer.allowed(v, now));

  reset(); writer.send(Op::unknown_time, now); v = observe("unknown_time");
  check("unknown_time_blocks", v.validity == Validity::unknown && !consumer.issue(v, now));
  reset(); writer.send(Op::verify, 50); v = observe("future_evidence");
  check("future_time_not_assumed_fresh", v.validity == Validity::unknown);

  reset(); v = observe("before_issue"); require(consumer.issue(v, now), "issue");
  now = command_lifetime; writer.send(Op::snapshot, now); v = observe("fresh_data_old_intent");
  check("new_data_does_not_extend_deadline", consumer.execute(v, now) == "expired");
  reset(); v = observe("new_intent"); require(consumer.issue(v, now), "issue");
  writer.send(Op::restart_epoch, now); v = observe("new_authority_old_view");
  check("old_view_rejected_after_restart", v.validity == Validity::old_epoch);
  writer.send(Op::snapshot, now); observe("new_epoch_snapshot");
  consumer.reconciled = true; now = stable_period; v = observe("new_epoch_recovered");
  check("old_epoch_intent_rejected", consumer.execute(v, now) == "old_epoch");
  reset(); v = observe("duplicate_submission"); require(consumer.issue(v, now), "issue");
  check("first_submit_is_unknown", consumer.execute(v, now) == "unknown");
  check("unknown_does_not_resubmit", consumer.execute(v, now) == "no_resubmit" && !consumer.issue(v, now));

  reset(); trace.flush(); results.flush();
  writer.crash(); v = observe("writer_died_mid_publication");
  check("owner_death_invalidates_torn_record", v.validity == Validity::damaged && !consumer.allowed(v, now));
  trace.flush(); results.flush(); writer.start();
  writer.send(Op::restart_epoch, now); writer.send(Op::snapshot, now); v = observe("new_writer_snapshot");
  check("replacement_writer_does_not_auto_resume", v.usable() && !consumer.allowed(v, now));
  consumer.reconciled = true; now = stable_period; v = observe("replacement_writer_reconciled");
  check("replacement_writer_recovers_after_checks", consumer.allowed(v, now));

  reset(); constexpr std::uint64_t sample_count = 5000;
  writer.begin(Op::stress, now, sample_count);
  bool intact = true, monotonic = true; std::uint64_t previous = 0, changes = 0;
  for (std::uint64_t i = 0; i < sample_count; ++i) {
    v = observe("concurrent_snapshot");
    intact = intact && v.record.checksum == checksum(v.record) && v.usable();
    monotonic = monotonic && v.record.version >= previous;
    if (v.record.version != previous) ++changes;
    previous = v.record.version;
    if (i % 100 == 0) std::this_thread::sleep_for(std::chrono::microseconds(100));
  }
  writer.finish(); v = observe("stress_complete");
  check("concurrent_snapshots_are_complete", intact);
  check("versions_never_regress", monotonic);
  check("concurrent_run_observed_changes", changes > 1 && v.record.version == sample_count + 1);
  writer.stop(); trace.flush(); results.flush();
  require(trace.good() && results.good(), "evidence write failure");
  std::ofstream summary(output / "summary.json");
  summary << "{\"prototype\":true,\"platform\":\"Linux\",\"checks_passed\":" << checks
          << ",\"publications\":" << sample_count << ",\"concurrent_reads\":" << sample_count
          << ",\"observed_versions\":" << changes
          << ",\"clock\":\"injected logical milliseconds\",\"capacity_claim\":false}\n";
  summary.flush(); require(summary.good(), "summary write failure");
  std::cout << "Completed " << checks << " checks. Evidence: " << output << '\n';
  return 0;
}
int main(int argc, char** argv) {
  signal(SIGPIPE, SIG_IGN);
  try {
    require(argc == 2, "Usage: freshness_probe NEW_EVIDENCE_DIRECTORY");
    return run(argv[1]);
  } catch (const std::exception& e) {
    std::cerr << "FAIL: " << e.what() << '\n'; return 1;
  }
}
