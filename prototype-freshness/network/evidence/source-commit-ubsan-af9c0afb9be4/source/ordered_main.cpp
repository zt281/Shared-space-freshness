// PROTOTYPE: one publisher, two consumer processes, real shared memory + local journal.
#include "ordered_consumer.hpp"
#include "experiment.hpp"
#include <optional>
#include <sys/resource.h>

enum class Action { inspect, consume, reject_event, capture, reconcile, stop, resume, issue, execute, quit };
struct Command { Action action; Tick now; std::uint64_t budget; };
struct Reply {
  std::uint64_t cursor = 0, head = 0, processed = 0, journal_reads = 0, alerts = 0, cancellations = 0;
  bool allowed = false, complete = false, success = false;
  char outcome[32]{};
};

// Control pipes carry experiment commands and status only; business events come from Space.
class ReaderProcess {
  Space& space;
  std::filesystem::path directory;
  pid_t pid = -1;
  int request = -1, response = -1;
  void worker(int in, int out) {
    OrderedConsumer consumer(space);
    std::optional<Consumer::RecoveryTicket> ticket;
    std::ofstream states(directory / "states.jsonl"), events(directory / "events.jsonl"), views(directory / "views.jsonl");
    require(states.good() && events.good() && views.good(), "consumer evidence files");
    for (;;) {
      Command command{};
      transfer(in, &command, sizeof(command), false);
      if (command.action == Action::quit) return;
      Reply reply{};
      switch (command.action) {
        case Action::consume:
        case Action::reject_event:
          reply.success = consumer.consume(command.now, command.budget, [&](const Change& event) {
            const bool accepted = command.action != Action::reject_event;
            const auto& r = event.record;
            events << "{\"pid\":" << getpid() << ",\"sequence\":" << event.sequence
                   << ",\"accepted\":" << (accepted ? "true" : "false")
                   << ",\"logical_ms\":" << command.now << ",\"epoch\":" << r.epoch
                   << ",\"version\":" << r.version << ",\"proof\":" << r.proof
                   << ",\"value_ms\":" << r.value_time << ",\"verified_ms\":" << r.verified_time
                   << ",\"received_ms\":" << r.received_time << ",\"price\":" << r.price
                   << ",\"quantity\":" << r.quantity << ",\"checksum\":" << r.checksum
                   << ",\"gap\":" << r.gap << ",\"time_known\":" << r.time_known
                   << ",\"seal\":" << event.seal << "}\n";
            events.flush(); require(events.good(), "complete consumer event evidence");
            return accepted;
          });
          break;
        case Action::capture: ticket = consumer.recovery_ticket(command.now); reply.success = true; break;
        case Action::reconcile: reply.success = ticket && consumer.reconcile(*ticket, command.now); break;
        case Action::stop: consumer.stop(); reply.success = true; break;
        case Action::resume: consumer.resume(); reply.success = true; break;
        case Action::issue: reply.success = consumer.issue(command.now); break;
        case Action::execute: {
          const auto result = consumer.execute(command.now);
          result.copy(reply.outcome, sizeof(reply.outcome) - 1);
          break;
        }
        case Action::inspect: break;
        default: throw std::runtime_error("unexpected consumer command");
      }
      const auto s = consumer.status(command.now);
      reply.cursor = s.cursor; reply.head = s.head; reply.processed = s.processed;
      reply.journal_reads = s.journal_reads; reply.alerts = s.alerts;
      reply.cancellations = s.cancellation_attempts; reply.allowed = s.allowed; reply.complete = s.complete;
      write_event(views, "current_source", command.now, s.source);
      rusage usage{};
      require(getrusage(RUSAGE_SELF, &usage) == 0, "consumer resource observation");
      states << "{\"pid\":" << getpid() << ",\"action\":" << static_cast<int>(command.action)
             << ",\"logical_ms\":" << command.now << ",\"budget\":" << command.budget
             << ",\"cursor\":" << s.cursor << ",\"head\":" << s.head << ",\"backlog\":" << s.backlog
             << ",\"processed\":" << s.processed << ",\"journal_reads\":" << s.journal_reads
             << ",\"alerts\":" << s.alerts << ",\"simulated_cancel_attempts\":" << s.cancellation_attempts
             << ",\"simulated_cancel_result\":\"" << (s.cancellation_attempts ? "unknown" : "not_attempted") << "\""
             << ",\"allowed\":" << s.allowed << ",\"recovering\":" << s.recovering
             << ",\"complete\":" << s.complete << ",\"success\":" << reply.success
             << ",\"user_cpu_us\":" << usage.ru_utime.tv_sec * 1000000LL + usage.ru_utime.tv_usec
             << ",\"system_cpu_us\":" << usage.ru_stime.tv_sec * 1000000LL + usage.ru_stime.tv_usec
             << ",\"max_rss_kib\":" << usage.ru_maxrss
             << ",\"outcome\":\"" << reply.outcome << "\"}\n";
      states.flush(); views.flush();
      require(states.good() && views.good(), "consumer state evidence");
      transfer(out, &reply, sizeof(reply), true);
    }
  }
public:
  ReaderProcess(Space& source, const std::filesystem::path& path) : space(source), directory(path) {
    std::filesystem::create_directories(directory);
    int requests[2], responses[2];
    require(pipe(requests) == 0, "reader request pipe");
    if (pipe(responses) != 0) { close(requests[0]); close(requests[1]); throw std::runtime_error("reader response pipe"); }
    pid = fork();
    if (pid < 0) {
      close(requests[0]); close(requests[1]); close(responses[0]); close(responses[1]);
      throw std::runtime_error("fork reader");
    }
    if (pid == 0) {
      close(requests[1]); close(responses[0]);
      try { worker(requests[0], responses[1]); _exit(0); }
      catch (const std::exception& e) { std::cerr << e.what() << '\n'; _exit(2); }
    }
    close(requests[0]); close(responses[1]);
    request = requests[1]; response = responses[0];
  }
  ReaderProcess(const ReaderProcess&) = delete;
  ReaderProcess& operator=(const ReaderProcess&) = delete;
  pid_t process_id() const { return pid; }
  Reply send(Action action, Tick now, std::uint64_t budget = 0) {
    Command c{action, now, budget}; transfer(request, &c, sizeof(c), true);
    Reply r{}; transfer(response, &r, sizeof(r), false); return r;
  }
  void stop() {
    Command c{Action::quit, 0, 0}; transfer(request, &c, sizeof(c), true);
    int status = 0; require(waitpid(pid, &status, 0) == pid, "wait reader"); pid = -1;
    require(WIFEXITED(status) && WEXITSTATUS(status) == 0, "reader failed");
  }
  ~ReaderProcess() {
    if (pid > 0) { kill(pid, SIGTERM); int status = 0; waitpid(pid, &status, 0); }
    if (request >= 0) close(request);
    if (response >= 0) close(response);
  }
};

int run_ordered(const std::filesystem::path& root) {
  require(!std::filesystem::exists(root), "choose a new evidence directory");
  std::filesystem::create_directories(root);
  std::ofstream results(root / "results.jsonl");
  int checks = 0;
  const auto check = [&](const char* name, bool pass) {
    ++checks;
    results << "{\"check\":\"" << name << "\",\"passed\":" << (pass ? "true" : "false") << "}\n";
    results.flush(); require(results.good(), "result evidence");
    require(pass, std::string("ordered scenario: ") + name);
    std::cout << "PASS " << name << '\n';
  };
  {
    const auto dir = root / "lag-and-recovery"; std::filesystem::create_directories(dir);
    Space space(dir / "PROTOTYPE-events.bin");
    Publisher writer(space, dir);
    ReaderProcess fast(space, dir / "fast"), slow(space, dir / "slow");
    check("three_distinct_business_processes", writer.process_id() != fast.process_id() &&
          writer.process_id() != slow.process_id() && fast.process_id() != slow.process_id());
    check("old_pending_intent_created", slow.send(Action::issue, 0).success);
    check("healthy_intent_created", fast.send(Action::issue, 0).success);
    check("healthy_submission_unknown", std::string(fast.send(Action::execute, 0).outcome) == "unknown");
    bool fast_continues = true;
    for (std::uint64_t i = 1; i <= 24; ++i) {
      const Tick now = static_cast<Tick>(i * 20);
      writer.send(Op::draft, now); writer.send(Op::publish, now);
      const auto f = fast.send(Action::consume, now, 1);
      const auto s = slow.send(Action::inspect, now);
      fast_continues = fast_continues && f.allowed && f.cursor == i && f.processed == i;
      if (i == 3) check("below_demo_lag_threshold_no_recovery_latch", s.alerts == 0);
      if (i == 4) check("threshold_restricts_slow_group_only", !s.allowed && s.alerts == 1 && s.cancellations == 1 && f.allowed);
    }
    check("healthy_consumer_keeps_processing_every_event", fast_continues);
    const auto held = slow.send(Action::capture, 480);
    check("slow_progress_not_silently_moved", held.cursor == 0 && held.head == 24);
    check("fresh_snapshot_does_not_prove_catchup", !held.allowed);
    check("cannot_reconcile_before_required_events", !slow.send(Action::reconcile, 480).success);
    slow.send(Action::stop, 480);
    Reply caught{};
    for (int batch = 0; batch < 6; ++batch) caught = slow.send(Action::consume, 600, 4);
    check("slow_consumed_all_events_in_order", caught.cursor == 24 && caught.processed == 24);
    check("evicted_events_recovered_from_complete_journal", caught.journal_reads == 16);
    check("catchup_alone_does_not_resume", !caught.allowed);
    check("current_reconciliation_accepted", slow.send(Action::reconcile, 600).success);
    check("manual_stop_survives_catchup_and_stability", !slow.send(Action::inspect, 800).allowed);
    check("explicit_resume_after_all_conditions", slow.send(Action::resume, 800).allowed);
    check("catchup_does_not_resubmit_expired_intent", std::string(slow.send(Action::execute, 800).outcome) == "expired");
    check("unknown_intent_not_repeated_after_catchup", std::string(fast.send(Action::execute, 800).outcome) == "no_resubmit");
    check("healthy_consumer_never_needed_archive", fast.send(Action::inspect, 800).journal_reads == 0);
    slow.stop(); fast.stop(); writer.stop();
  }
  {
    const auto dir = root / "missing-record"; std::filesystem::create_directories(dir);
    Space space(dir / "PROTOTYPE-events.bin"); Publisher writer(space, dir);
    ReaderProcess fast(space, dir / "fast"), slow(space, dir / "slow");
    for (int i = 1; i <= 12; ++i) {
      writer.send(Op::draft, i); writer.send(Op::publish, i);
      fast.send(Action::consume, i, 1);
    }
    check("healthy_before_missing_record_detected", fast.send(Action::inspect, 12).allowed);
    slow.send(Action::capture, 12);
    experiment::Faults::truncate_journal(space, 1); // Only this newly created scratch file.
    const auto missing = slow.send(Action::consume, 12, 4);
    check("missing_record_returns_explicit_failure", !missing.success && !missing.complete);
    check("failed_batch_does_not_advance_cursor", missing.cursor == 0 && missing.processed == 0);
    check("common_record_failure_restricts_healthy_group", !fast.send(Action::inspect, 12).allowed);
    check("missing_record_cannot_be_reconciled_away", !slow.send(Action::reconcile, 12).success);
    writer.send(Op::snapshot, 12);
    const auto after = slow.send(Action::inspect, 12);
    check("snapshot_cannot_erase_missing_required_events", !after.allowed && !after.complete && after.head == 12);
    slow.stop(); fast.stop(); writer.stop();
  }
  {
    const auto dir = root / "journal-capacity"; std::filesystem::create_directories(dir);
    Space space(dir / "PROTOTYPE-events.bin"); Publisher writer(space, dir);
    ReaderProcess fast(space, dir / "fast"), slow(space, dir / "slow");
    for (int i = 1; i <= 3; ++i) {
      writer.send(Op::draft, i); writer.send(Op::publish, i);
      fast.send(Action::consume, i, 1); slow.send(Action::consume, i, 1);
    }
    check("both_ready_before_journal_capacity_failure", fast.send(Action::inspect, 3).allowed && slow.send(Action::inspect, 3).allowed);
    experiment::Faults::limit_journal(space, 3); // Configured experiment record quota, not a real disk-full test.
    writer.send(Op::draft, 4); writer.send(Op::rejected_publish, 4);
    const auto a = fast.send(Action::inspect, 4), b = slow.send(Action::inspect, 4);
    check("unsaved_event_never_advertised", a.head == 3 && b.head == 3 && space.read(4).record.version == 4);
    check("common_capacity_failure_blocks_both", !a.allowed && !b.allowed && !a.complete && !b.complete);
    check("common_failure_simulates_cancel_and_alert", a.alerts == 1 && b.alerts == 1 && a.cancellations == 1 && b.cancellations == 1);
    check("common_failure_rejects_new_intents", !fast.send(Action::issue, 4).success && !slow.send(Action::issue, 4).success);
    slow.stop(); fast.stop(); writer.stop();
  }
  {
    const auto dir = root / "processing-failure"; std::filesystem::create_directories(dir);
    Space space(dir / "PROTOTYPE-events.bin"); Publisher writer(space, dir);
    ReaderProcess fast(space, dir / "fast"), slow(space, dir / "slow");
    writer.send(Op::draft, 1); writer.send(Op::publish, 1);
    check("healthy_processes_while_peer_rejects", fast.send(Action::consume, 1, 1).allowed);
    const auto refused = slow.send(Action::reject_event, 1, 1);
    check("processing_failure_does_not_ack_event", !refused.success && refused.cursor == 0 && !refused.allowed);
    slow.send(Action::capture, 1);
    const auto retry = slow.send(Action::consume, 1, 1);
    check("retry_processes_same_required_event", retry.cursor == 1 && retry.processed == 1);
    check("processed_event_not_delivered_again", slow.send(Action::consume, 1, 1).processed == 1);
    check("local_failure_does_not_restrict_peer", fast.send(Action::inspect, 1).allowed);
    check("processing_recovery_requires_reconciliation", !retry.allowed && slow.send(Action::reconcile, 1).success);
    writer.send(Op::draft, 100); writer.send(Op::publish, 100);
    fast.send(Action::consume, 100, 1);
    check("normal_new_event_does_not_restart_recovery", slow.send(Action::consume, 100, 1).cursor == 2);
    check("processing_recovery_requires_stability", !slow.send(Action::inspect, 200).allowed && slow.send(Action::inspect, 201).allowed);
    slow.stop(); fast.stop(); writer.stop();
  }
  std::ofstream summary(root / "summary.json");
  rusage usage{}; require(getrusage(RUSAGE_CHILDREN, &usage) == 0, "child resource summary");
  summary << "{\"prototype\":true,\"checks_passed\":" << checks
          << ",\"buffer_capacity\":8,\"lag_threshold\":4,\"consumer_processes\":2"
          << ",\"children_user_cpu_us\":" << usage.ru_utime.tv_sec * 1000000LL + usage.ru_utime.tv_usec
          << ",\"children_system_cpu_us\":" << usage.ru_stime.tv_sec * 1000000LL + usage.ru_stime.tv_usec
          << ",\"children_max_rss_kib\":" << usage.ru_maxrss
          << ",\"capacity_claim\":false,\"network_validated\":false}\n";
  summary.flush(); require(summary.good(), "summary evidence");
  std::cout << "Completed " << checks << " ordered checks. Evidence: " << root << '\n';
  return 0;
}
int main(int argc, char** argv) {
  signal(SIGPIPE, SIG_IGN);
  try { require(argc == 2, "Usage: ordered_probe NEW_EVIDENCE_DIRECTORY"); return run_ordered(argv[1]); }
  catch (const std::exception& e) { std::cerr << "FAIL: " << e.what() << '\n'; return 1; }
}
