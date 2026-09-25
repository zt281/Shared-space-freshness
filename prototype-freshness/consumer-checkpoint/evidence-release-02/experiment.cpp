// THROWAWAY PROTOTYPE: local persistence/recovery experiment, no trading connection.
#include <algorithm>
#include <array>
#include <cerrno>
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>
#include <fcntl.h>
#include <sys/wait.h>
#include <unistd.h>

namespace fs = std::filesystem;
using U = std::uint64_t;
using Words = std::vector<U>;
using Clock = std::chrono::steady_clock;
constexpr U seed = 1469598103934665603ULL;
constexpr U magic = 0x5459434845505231ULL;
constexpr U algorithm = 1;
U mix(U h, U v) { return (h ^ v) * 1099511628211ULL; }
U hash(const Words& w) { U h = seed; for (U v : w) h = mix(h, v); return h; }
void need(bool ok, const std::string& why) { if (!ok) throw std::runtime_error(why); }
double ms(Clock::duration d) { return std::chrono::duration<double, std::milli>(d).count(); }

// Each scenario owns one private directory, one consumer and one writer at a time.
// Canonical file: native little-endian u64 words; no cross-platform ABI promise.
// Fault points: 1 partial write, 2 complete write, 3 file sync, 4 rename,
// 5 directory sync, 6 injected ENOSPC before write, 7 EIO after rename.
U synchronizations = 0;
void sync_fd(int fd, bool directory = false) {
  int rc;
  do { rc = directory ? fsync(fd) : fdatasync(fd); } while (rc < 0 && errno == EINTR);
  need(rc == 0, "synchronization failed"); ++synchronizations;
}
void die_at(int fault, int point) { if (fault == point) _exit(77); }
void write_all(int fd, const void* p, std::size_t n) {
  const auto* b = static_cast<const char*>(p);
  while (n) {
    const auto k = write(fd, b, n);
    if (k < 0 && errno == EINTR) continue;
    need(k > 0, "write failed"); b += k; n -= static_cast<std::size_t>(k);
  }
}
void save(const fs::path& path, U kind, const Words& body, int fault = 0) {
  if (fault == 6) throw std::runtime_error("injected ENOSPC before write");
  Words data{magic, kind, static_cast<U>(body.size())};
  data.insert(data.end(), body.begin(), body.end()); data.push_back(hash(data));
  static U serial = 0;
  const auto temp = path.string() + ".pending-" + std::to_string(getpid()) + "-" + std::to_string(++serial);
  int fd = open(temp.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
  need(fd >= 0, "open staging file");
  try {
    if (fault == 1) { write_all(fd, data.data(), data.size() * 4); _exit(77); }
    write_all(fd, data.data(), data.size() * 8); die_at(fault, 2);
    sync_fd(fd); die_at(fault, 3);
    need(rename(temp.c_str(), path.c_str()) == 0, "rename checkpoint"); die_at(fault, 4);
    if (fault == 7) throw std::runtime_error("injected EIO after rename");
    const int dir = open(path.parent_path().c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    need(dir >= 0, "open directory");
    try { sync_fd(dir, true); } catch (...) { close(dir); throw; }
    close(dir); die_at(fault, 5);
  } catch (...) { close(fd); throw; }
  close(fd);
}
Words read(const fs::path& path, U kind) {
  std::ifstream stream(path, std::ios::binary);
  need(stream.good(), "missing evidence: " + path.filename().string());
  const auto bytes = fs::file_size(path);
  need(bytes >= 32 && bytes % 8 == 0 && bytes < 1024 * 1024, "invalid record length");
  Words w(bytes / 8);
  stream.read(reinterpret_cast<char*>(w.data()), static_cast<std::streamsize>(bytes));
  need(stream.good(), "short record");
  const U seal = w.back(); w.pop_back();
  need(w[0] == magic && w[1] == kind && w[2] == w.size() - 3 && hash(w) == seal,
       "record identity or checksum mismatch");
  return Words(w.begin() + 3, w.end());
}
struct Event { U seq, price, quantity, parameter, fit; };
Words flatten(const Event& e) { return {e.seq, e.price, e.quantity, e.parameter, e.fit}; }
struct State { U cursor = 0, sum = 0, chain = seed; };
State step(State s, const Event& e) {
  need(e.seq == s.cursor + 1, "input gap");
  ++s.cursor; s.sum += e.price * e.quantity + e.parameter + e.fit;
  s.chain = mix(s.chain, hash(flatten(e))); return s;
}
Words encode(State s) { return {algorithm, s.cursor, s.sum, s.chain}; }
bool same(State a, State b) { return encode(a) == encode(b); }
std::vector<Event> inputs(const fs::path& dir) {
  const auto w = read(dir / "PROTOTYPE-inputs.bin", 1);
  need(w.size() >= 2 && w[0] == algorithm && w.size() == 2 + w[1] * 5, "unsupported computation/input version");
  std::vector<Event> out;
  for (U i = 0; i < w[1]; ++i) {
    const auto p = 2 + i * 5; need(w[p] == i + 1, "input sequence mismatch");
    out.push_back({w[p], w[p+1], w[p+2], w[p+3], w[p+4]});
  }
  return out;
}
State prefix(const std::vector<Event>& events, U count) {
  need(count <= events.size(), "checkpoint beyond retained inputs");
  State s; for (U i = 0; i < count; ++i) s = step(s, events[i]); return s;
}
void initialize(const fs::path& dir, U count = 24) {
  need(fs::create_directory(dir), "scenario directory already exists");
  Words w{algorithm, count};
  for (U i = 1; i <= count; ++i) {
    // Parameter and fitting values change inside replay suffixes, not just prices.
    auto event = flatten({i, 100 + i, 1 + i % 3, 10 + i / 4, 200 + i * 7});
    w.insert(w.end(), event.begin(), event.end());
  }
  save(dir / "PROTOTYPE-inputs.bin", 1, w);
  save(dir / "PROTOTYPE-checkpoint.bin", 2, encode({}));
  save(dir / "PROTOTYPE-stop.bin", 3, {0, 0});
}
struct Consumer {
  fs::path dir;
  std::vector<Event> events;
  State saved, working;
  U max_events = 64, max_bytes = 64 * sizeof(Event);
  bool failed = false, stopped = false, reconciled = false, fresh = false, unknown = false;
  Clock::time_point dirty_since{};
  explicit Consumer(fs::path d) : dir(std::move(d)), events(inputs(dir)) {
    auto checkpoint = read(dir / "PROTOTYPE-checkpoint.bin", 2);
    need(checkpoint.size() == 4 && checkpoint[0] == algorithm, "invalid checkpoint version");
    saved = {checkpoint[1], checkpoint[2], checkpoint[3]};
    need(same(saved, prefix(events, saved.cursor)), "checkpoint state differs from retained prefix");
    working = saved;
    auto control = read(dir / "PROTOTYPE-stop.bin", 3);
    need(control.size() == 2 && control[1] <= 1, "invalid stop record");
    stopped = control[1];
    if (fs::exists(dir / "PROTOTYPE-intent.bin")) {
      auto intent = read(dir / "PROTOTYPE-intent.bin", 4);
      need(intent.size() == 7 && intent[0] == 1 && intent[1] == 1 &&
           intent[2] > 0 && intent[2] <= events.size() && intent[6] >= 1 && intent[6] <= 4,
           "invalid intent identity/state");
      need(intent[3] == prefix(events, intent[2]).chain &&
           intent[4] == hash(flatten(events[intent[2]-1])) && intent[5] == events[intent[2]-1].quantity,
           "intent recovery evidence mismatch");
      if (intent[6] == 1) { intent[6] = 4; save(dir / "PROTOTYPE-intent.bin", 4, intent); }
      unknown = intent[6] == 2;
    }
  }
  U pending() const { return working.cursor - saved.cursor; }
  bool at_bound() const { return pending() >= max_events || (pending() + 1) * sizeof(Event) > max_bytes; }
  bool allowed() const { return !failed && !stopped && !unknown && reconciled && fresh && !at_bound(); }
  void observe(const std::string& label) const {
    std::ofstream out(dir / "observations.jsonl", std::ios::app);
    out << "{\"label\":\"" << label << "\",\"saved\":" << saved.cursor
        << ",\"computed\":" << working.cursor << ",\"sum\":" << working.sum
        << ",\"chain\":" << working.chain << ",\"pending\":" << pending()
        << ",\"pending_bytes\":" << pending()*sizeof(Event) << ",\"failed\":" << failed
        << ",\"stopped\":" << stopped << ",\"unknown\":" << unknown
        << ",\"reconciled\":" << reconciled << ",\"fresh\":" << fresh
        << ",\"allowed\":" << allowed() << "}\n";
  }
  bool consume_one() {
    if (failed || at_bound() || working.cursor == events.size()) return false;
    if (pending() == 0) dirty_since = Clock::now();
    working = step(working, events[working.cursor]); return true;
  }
  void consume_to(U n) { while (working.cursor < n) need(consume_one(), "consume blocked"); }
  bool flush(int fault = 0) {
    if (failed) return false;
    if (!pending()) return true;
    try { save(dir / "PROTOTYPE-checkpoint.bin", 2, encode(working), fault); saved = working; return true; }
    catch (const std::exception&) { failed = true; reconciled = false; return false; }
  }
  bool due(U batch, std::chrono::milliseconds age) const {
    return pending() && (pending() >= batch || Clock::now() - dirty_since >= age);
  }
  bool reconcile(bool current_inputs_valid) {
    fresh = current_inputs_valid;
    reconciled = !failed && !unknown && working.cursor == events.size();
    return allowed();
  }
  bool stop(int fault = 0) {
    stopped = true;
    try {
      const auto old = read(dir / "PROTOTYPE-stop.bin", 3);
      save(dir / "PROTOTYPE-stop.bin", 3, {old[0] + 1, 1}, fault); return true;
    } catch (const std::exception&) { failed = true; return false; }
  }
  bool publish(int fault = 0) {
    if (failed) return false;
    try { save(dir / "PROTOTYPE-result.bin", 5, encode(working), fault); return true; }
    catch (const std::exception&) { failed = true; return false; }
  }
  bool prepare(int fault = 0) {
    if (!allowed() || fs::exists(dir / "PROTOTYPE-intent.bin") || working.cursor == 0) return false;
    const auto& e = events[working.cursor-1];
    // Fixed environment + consumer + event/cycle identity; one intent slot in this experiment.
    try { save(dir / "PROTOTYPE-intent.bin", 4,
               {1, 1, e.seq, working.chain, hash(flatten(e)), e.quantity, 1}, fault); }
    catch (const std::exception&) { failed = true; return false; }
    return true;
  }
  bool submit(int fault = 0, int save_fault = 0) {
    if (!allowed()) return false;
    auto intent = read(dir / "PROTOTYPE-intent.bin", 4);
    if (intent[6] != 1) return false;
    die_at(fault, 1); // Proven unattempted intent survives; recovery retires it.
    intent[6] = 2;
    try { save(dir / "PROTOTYPE-intent.bin", 4, intent, save_fault); }
    catch (const std::exception&) { failed = true; return false; }
    unknown = true;
    die_at(fault, 2); // May have sent: deliberately indistinguishable to recovery.
    U calls = 0;
    if (fs::exists(dir / "PROTOTYPE-broker.bin")) calls = read(dir / "PROTOTYPE-broker.bin", 6)[1];
    // Mock external system does NOT deduplicate: an erroneous retry increments calls.
    save(dir / "PROTOTYPE-broker.bin", 6, {intent[2], calls + 1});
    die_at(fault, 3);
    intent[6] = 3; save(dir / "PROTOTYPE-intent.bin", 4, intent); unknown = false;
    return true;
  }
  bool query_broker() {
    if (!unknown || !fs::exists(dir / "PROTOTYPE-broker.bin")) return false;
    auto intent = read(dir / "PROTOTYPE-intent.bin", 4);
    const auto broker = read(dir / "PROTOTYPE-broker.bin", 6);
    need(broker.size() == 2 && broker[0] == intent[2] && broker[1] == 1, "external record mismatch");
    intent[6] = 3; save(dir / "PROTOTYPE-intent.bin", 4, intent); unknown = false;
    return true;
  }
};

std::ofstream checks;
U passed = 0;
void check(const std::string& name, bool ok) {
  checks << "{\"check\":\"" << name << "\",\"pass\":" << (ok ? "true" : "false") << "}\n";
  checks.flush(); need(ok, name); ++passed;
}
void crash(const std::string& name, const std::function<void()>& action) {
  std::cout.flush(); checks.flush(); const pid_t pid = fork(); need(pid >= 0, "fork");
  if (pid == 0) { try { action(); _exit(78); } catch (...) { _exit(79); } }
  int status = 0; need(waitpid(pid, &status, 0) == pid, "waitpid");
  check(name + ": actual child process death", WIFEXITED(status) && WEXITSTATUS(status) == 77);
}
void checkpoint_cases(const fs::path& root) {
  for (int point = 0; point <= 5; ++point) {
    const auto name = "checkpoint-crash-" + std::to_string(point); const auto d = root / name;
    initialize(d);
    { Consumer c(d); c.consume_to(8); need(c.flush(), "initial flush"); }
    crash(name, [&] { Consumer c(d); c.consume_to(16); c.observe("before-crash"); if (point == 0) _exit(77); c.flush(point); });
    fs::copy_file(d / "PROTOTYPE-checkpoint.bin", d / "checkpoint-at-crash.bin");
    Consumer c(d);
    c.observe("recovered");
    check(name + ": canonical prefix recovered", c.saved.cursor == (point < 4 ? 8U : 16U));
    check(name + ": permission not restored", !c.allowed());
    c.consume_to(24);
    check(name + ": exact replay state", same(c.working, prefix(c.events, 24)));
    check(name + ": replay does not submit", !fs::exists(d / "PROTOTYPE-broker.bin"));
    check(name + ": catchup alone cannot trade", !c.allowed());
    check(name + ": stale evidence cannot trade", !c.reconcile(false));
    check(name + ": current reconciliation allows", c.reconcile(true));
    check(name + ": save final replay", c.flush());
    c.observe("final");
  }
}
void action_cases(const fs::path& root) {
  for (int point = 1; point <= 3; ++point) {
    const auto name = "submission-crash-" + std::to_string(point); const auto d = root / name;
    initialize(d, 8);
    crash(name, [&] { Consumer c(d); c.consume_to(8); need(c.reconcile(true), "current");
      need(c.prepare(), "prepare"); c.observe("prepared"); c.submit(point); });
    Consumer c(d); check(name + ": computation checkpoint lags", c.saved.cursor == 0);
    c.consume_to(8); c.reconcile(true);
    auto intent = read(d / "PROTOTYPE-intent.bin", 4);
    check(name + ": stable identity and risk", intent[2] == 8 && intent[3] == c.working.chain && intent[5] == 3);
    check(name + ": replay cannot replace existing intent", !c.prepare());
    check(name + ": no automatic resubmission", !c.submit());
    check(name + ": recovery outcome", intent[6] == (point == 1 ? 4U : 2U));
    if (point == 3) {
      check(name + ": unknown gates trading", !c.allowed());
      check(name + ": query resolves actual mock submission", c.query_broker());
      check(name + ": mock called once", read(d / "PROTOTYPE-broker.bin", 6)[1] == 1);
      check(name + ": resolved intent still cannot resend", !c.submit());
    } else {
      check(name + ": no mock call", !fs::exists(d / "PROTOTYPE-broker.bin"));
      if (point == 2) check(name + ": absent broker evidence remains unknown", !c.query_broker() && !c.allowed());
    }
    check(name + ": recovery checkpoint saves", c.flush());
    c.observe("recovered");
  }
  const auto d = root / "normal-submission"; initialize(d, 8); Consumer c(d); c.consume_to(8);
  check("normal: fresh reconciliation", c.reconcile(true));
  check("normal: prepare and submit without computation checkpoint", c.prepare() && c.submit() && c.saved.cursor == 0);
  check("normal: successful intent cannot repeat", !c.submit());
  check("normal: exactly one mock call observed", read(d / "PROTOTYPE-broker.bin", 6)[1] == 1);
  check("normal: final flush", c.flush());
  for (const bool attempt : {false, true}) for (int failure : {6, 7}) {
    const auto name = std::string(attempt ? "attempt-save-" : "intent-save-") + std::to_string(failure);
    const auto path = root / name; initialize(path, 8); Consumer writer(path);
    writer.consume_to(8); writer.reconcile(true);
    if (attempt) need(writer.prepare(), "prepare before attempt failure");
    check(name + ": save failure reported", attempt ? !writer.submit(0, failure) : !writer.prepare(failure));
    check(name + ": no submission after failed save", !fs::exists(path / "PROTOTYPE-broker.bin") && !writer.allowed());
    writer.observe("failure");
    Consumer recovered(path); recovered.consume_to(8);
    check(name + ": restart remains restricted", !recovered.allowed());
    if (fs::exists(path / "PROTOTYPE-intent.bin")) {
      const auto intent = read(path / "PROTOTYPE-intent.bin", 4);
      check(name + ": uncertain write resolved by canonical record", intent[6] == (attempt && failure == 7 ? 2U : 4U));
    }
    recovered.observe("recovered");
  }
}
void boundary_cases(const fs::path& root) {
  for (const bool memory : {false, true}) {
    const std::string name = memory ? "memory-bound" : "event-bound"; const auto d = root / name;
    initialize(d, 8); Consumer c(d);
    if (memory) c.max_bytes = 4 * sizeof(Event); else c.max_events = 4;
    c.consume_to(4);
    check(name + ": refuses overflow", c.at_bound() && !c.consume_one() && c.pending() == 4);
    check(name + ": dependent orders gated", !c.allowed());
    c.observe("at-bound");
    check(name + ": save releases bound", c.flush() && !c.at_bound());
    c.consume_to(8); check(name + ": complete and save", c.flush());
    c.observe("saved");
  }
  for (int fault : {6, 7}) {
    const auto name = "save-failure-" + std::to_string(fault); const auto d = root / name;
    initialize(d, 8); Consumer c(d); c.consume_to(8); c.reconcile(true);
    check(name + ": failure observed", !c.flush(fault));
    check(name + ": consumer and trading stay restricted", !c.consume_one() && !c.allowed() && !c.prepare());
    c.observe("failure");
    fs::copy_file(d / "PROTOTYPE-checkpoint.bin", d / "checkpoint-at-failure.bin");
    Consumer recovery(d);
    check(name + ": canonical checkpoint validated", recovery.saved.cursor == (fault == 6 ? 0U : 8U));
    check(name + ": restart not permission", !recovery.allowed());
    recovery.consume_to(8); check(name + ": recover exact state", same(recovery.working, prefix(recovery.events, 8)));
    check(name + ": save restored", recovery.flush());
    recovery.observe("recovered");
  }
  { const auto d = root / "timer-flush"; initialize(d, 8); Consumer c(d); c.consume_to(1);
    check("timer: not count-triggered", c.pending() < 8);
    std::this_thread::sleep_for(std::chrono::milliseconds(3));
    check("timer: elapsed-time trigger", c.due(8, std::chrono::milliseconds(2)));
    check("timer: flush partial batch", c.flush() && c.saved.cursor == 1);
  }
  { const auto d = root / "stop-survives"; initialize(d, 8);
    crash("stop-survives", [&] { Consumer c(d); c.consume_to(8); need(c.stop(), "save stop"); _exit(77); });
    Consumer c(d); c.consume_to(8);
    check("stop: latest stop overrides old computation checkpoint", c.stopped && c.saved.cursor == 0 && !c.reconcile(true));
    check("stop: replay cannot clear stop", c.flush() && !c.allowed() && read(d / "PROTOTYPE-stop.bin", 3)[1] == 1);
    c.observe("recovered");
  }
  { const auto d = root / "stop-save-failure"; initialize(d, 8); Consumer c(d); c.consume_to(8); c.reconcile(true);
    check("stop failure: immediate stop without false durability acknowledgement", !c.stop(6) && c.stopped && !c.allowed());
    check("stop failure: disk still reflects last acknowledged control", read(d / "PROTOTYPE-stop.bin", 3)[1] == 0);
    c.observe("failure");
  }
}
void publication_cases(const fs::path& root) {
  for (int fault : {0, 3, 4}) {
    const auto name = "publication-" + std::to_string(fault); const auto d = root / name; initialize(d, 8);
    if (fault) crash(name, [&] { Consumer c(d); c.consume_to(8); c.publish(fault); });
    else { Consumer c(d); c.consume_to(8); check(name + ": publish before checkpoint", c.publish() && c.saved.cursor == 0); }
    Consumer c(d); check(name + ": producer checkpoint lags", c.saved.cursor == 0);
    if (fault == 3) {
      check(name + ": staged result unavailable to downstream", !fs::exists(d / "PROTOTYPE-result.bin"));
    } else {
      auto published = read(d / "PROTOTYPE-result.bin", 5);
      check(name + ": exact published version recoverable", published == encode(prefix(c.events, 8)));
      // Recovery confirms the canonical result is durable before downstream release.
      save(d / "PROTOTYPE-result.bin", 5, published);
      save(d / "PROTOTYPE-downstream.bin", 7, {8, hash(published)});
      c.consume_to(8); check(name + ": replay reproduces downstream version", published == encode(c.working));
      check(name + ": downstream use grants no producer trading permission", !c.allowed());
    }
  }
}
void missing_cases(const fs::path& root) {
  for (const std::string name : {"missing-input", "corrupt-input", "wrong-algorithm", "missing-checkpoint", "corrupt-checkpoint", "missing-stop", "wrong-intent"}) {
    const auto d = root / name; initialize(d, 8);
    if (name == "missing-input") fs::rename(d / "PROTOTYPE-inputs.bin", d / "retained-input.bin");
    if (name == "missing-checkpoint") fs::rename(d / "PROTOTYPE-checkpoint.bin", d / "retained-checkpoint.bin");
    if (name == "missing-stop") fs::rename(d / "PROTOTYPE-stop.bin", d / "retained-stop.bin");
    if (name == "corrupt-input" || name == "corrupt-checkpoint") {
      const auto p = d / (name == "corrupt-input" ? "PROTOTYPE-inputs.bin" : "PROTOTYPE-checkpoint.bin");
      std::ofstream damaged(p, std::ios::binary | std::ios::trunc); damaged << "injected damage";
    }
    if (name == "wrong-algorithm") { auto w = read(d / "PROTOTYPE-inputs.bin", 1); w[0] = 99; save(d / "PROTOTYPE-inputs.bin", 1, w); }
    if (name == "wrong-intent") save(d / "PROTOTYPE-intent.bin", 4, {1, 1, 8, 0, 0, 3, 2});
    bool rejected = false;
    try { Consumer c(d); } catch (const std::exception&) { rejected = true; }
    check(name + ": startup rejected without empty fallback", rejected);
    check(name + ": no external submission", !fs::exists(d / "PROTOTYPE-broker.bin"));
  }
}

// Finite open-loop schedule, 20 events every 100ms (200/s), all planned times retained.
// No QUIC, concurrent consumers, actual fitting, broker latency, or production durability claim.
void benchmark(const fs::path& root) {
  std::ofstream summary(root / "timings.csv");
  summary << "round,mode,events,checkpoint_commits,sync_calls,elapsed_ms,p50_durable_ms,p99_durable_ms,max_durable_ms,max_pending\n";
  for (int round = 0; round < 3; ++round) for (int order = 0; order < 2; ++order) {
    const bool batch = (round + order) % 2;
    const std::string mode = batch ? "batch8" : "per_event";
    const auto d = root / ("timing-" + std::to_string(round) + "-" + mode); initialize(d, 200);
    Consumer c(d); const U before = synchronizations;
    std::ofstream trace(d / "events.csv"); trace << "sequence,planned_ms,computed_ms,durable_ms\n";
    const auto start = Clock::now();
    std::vector<double> calculated(200), planned(200), latency;
    U commits = 0, high = 0;
    auto flush = [&] {
      const U prior = c.saved.cursor; check("timing flush " + d.filename().string() + " " + std::to_string(prior), c.flush());
      ++commits; const auto completed = ms(Clock::now() - start);
      for (U j = prior; j < c.saved.cursor; ++j) {
        latency.push_back(completed - planned[j]);
        trace << j+1 << ',' << planned[j] << ',' << calculated[j] << ',' << completed << '\n';
      }
    };
    for (U i = 0; i < 200; ++i) {
      const auto target = start + std::chrono::milliseconds((i / 20) * 100);
      if (Clock::now() < target && c.pending()) {
        std::this_thread::sleep_until(std::min(target, c.dirty_since + std::chrono::milliseconds(2)));
        if (c.due(8, std::chrono::milliseconds(2))) flush();
      }
      std::this_thread::sleep_until(target);
      planned[i] = ms(target - start);
      need(c.consume_one(), "benchmark input rejected"); calculated[i] = ms(Clock::now() - start);
      high = std::max(high, c.pending());
      if (!batch || c.due(8, std::chrono::milliseconds(2))) flush();
    }
    if (c.pending()) flush();
    const auto elapsed = ms(Clock::now() - start);
    check("timing exact final state " + d.filename().string(), same(c.saved, prefix(c.events, 200)));
    std::sort(latency.begin(), latency.end());
    summary << round << ',' << mode << ",200," << commits << ',' << synchronizations-before << ',' << elapsed
            << ',' << latency[99] << ',' << latency[197] << ',' << latency.back() << ',' << high << '\n';
  }
}
int main(int argc, char** argv) {
  try {
    need(argc == 2, "usage: checkpoint_experiment NEW_EVIDENCE_DIRECTORY");
    const fs::path root = fs::absolute(argv[1]); need(fs::create_directory(root), "evidence directory must be new");
    checks.open(root / "checks.jsonl");
    checkpoint_cases(root); action_cases(root); boundary_cases(root); publication_cases(root); missing_cases(root);
    benchmark(root);
    std::ofstream result(root / "summary.json"); result << "{\"checks_passed\":" << passed << ",\"status\":\"pass\"}\n";
    std::cout << "PASS " << passed << " checks; evidence: " << root << '\n';
  } catch (const std::exception& e) { std::cerr << "FAIL: " << e.what() << '\n'; return 1; }
}
