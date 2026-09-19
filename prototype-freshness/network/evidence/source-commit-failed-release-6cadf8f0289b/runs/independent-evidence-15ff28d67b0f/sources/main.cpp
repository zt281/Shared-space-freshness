#include "consumer.hpp"
#include "experiment.hpp"
#include <optional>

int run(const std::filesystem::path& output) {
  require(!std::filesystem::exists(output), "evidence directory already exists; choose a new path");
  std::filesystem::create_directories(output);
  Space space;
  Publisher writer(space, output);
  std::ofstream trace(output / "consumer.jsonl"), results(output / "results.jsonl");
  require(trace.good() && results.good(), "consumer evidence files");
  std::optional<Consumer> consumer(std::in_place);
  Tick now = 0;
  int checks = 0;
  auto observe = [&](const char* event) {
    auto v = space.read(now);
    consumer->observe(v, now);
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
  auto reset = [&]() { now = 0; writer.send(Op::reset, now); consumer.emplace(); };

  check("separate_processes", writer.process_id() != getpid());
  auto v = observe("initial");
  check("initial_usable", consumer->allowed(v, now));
  writer.send(Op::draft, 100);
  now = 100; v = observe("unpublished_draft");
  check("draft_not_visible", v.record.version == 1 && v.record.value_time == 0);
  writer.send(Op::publish, now); v = observe("complete_publish");
  check("complete_version_visible", v.record.version == 2 && v.record.checksum == checksum(v.record));

  reset(); now = warning_age; v = observe("warning_boundary");
  check("warning_still_usable", v.validity == Validity::warning && consumer->allowed(v, now));
  now = expiry_age; v = observe("expiry_boundary");
  check("expiry_blocks_new_intent", !consumer->issue(v, now) && v.validity == Validity::expired);
  writer.send(Op::replay, now); writer.send(Op::heartbeat, now); v = observe("old_copy_and_heartbeat");
  check("replay_and_heartbeat_do_not_renew", v.record.received_time == now && v.record.verified_time == 0 && !v.usable());
  writer.send(Op::verify, now); v = observe("source_business_verification");
  check("business_proof_renews_without_price_change", v.usable() && v.record.version == 1 && v.record.proof == 2 && !consumer->allowed(v, now));
  require(consumer->reconcile(consumer->recovery_ticket(v, now), v, now), "reconcile");
  now += stable_period; v = observe("reconciled_and_stable");
  check("recovery_requires_stable_period", consumer->allowed(v, now));

  reset(); consumer->stop();
  writer.send(Op::gap, now); observe("gap");
  writer.send(Op::verify, now); v = observe("proof_does_not_repair_gap");
  check("gap_requires_snapshot", v.validity == Validity::gap);
  writer.send(Op::snapshot, now); v = observe("full_snapshot");
  require(consumer->reconcile(consumer->recovery_ticket(v, now), v, now), "reconcile"); now = stable_period; v = observe("recovery_with_manual_stop");
  check("manual_stop_survives_recovery", !consumer->allowed(v, now));
  consumer->resume();
  check("explicit_resume", consumer->allowed(v, now));

  reset(); writer.send(Op::unknown_time, now); v = observe("unknown_time");
  check("unknown_time_blocks", v.validity == Validity::unknown && !consumer->issue(v, now));
  reset(); writer.send(Op::verify, 50); v = observe("future_evidence");
  check("future_time_not_assumed_fresh", v.validity == Validity::unknown);

  reset(); v = observe("before_issue"); require(consumer->issue(v, now), "issue");
  now = command_lifetime; writer.send(Op::snapshot, now); v = observe("fresh_data_old_intent");
  check("new_data_does_not_extend_deadline", consumer->execute(v, now) == "expired");
  reset(); v = observe("new_intent"); require(consumer->issue(v, now), "issue");
  writer.send(Op::restart_epoch, now); v = observe("new_authority_old_view");
  check("old_view_rejected_after_restart", v.validity == Validity::old_epoch);
  writer.send(Op::snapshot, now); v = observe("new_epoch_snapshot");
  require(consumer->reconcile(consumer->recovery_ticket(v, now), v, now), "reconcile"); now = stable_period; v = observe("new_epoch_recovered");
  check("old_epoch_intent_rejected", consumer->execute(v, now) == "old_epoch");
  reset(); v = observe("duplicate_submission"); require(consumer->issue(v, now), "issue");
  check("first_submit_is_unknown", consumer->execute(v, now) == "unknown");
  check("unknown_does_not_resubmit", consumer->execute(v, now) == "no_resubmit" && !consumer->issue(v, now));

  reset(); trace.flush(); results.flush();
  writer.crash(); v = observe("writer_died_mid_publication");
  check("owner_death_invalidates_torn_record", v.validity == Validity::damaged && !consumer->allowed(v, now));
  trace.flush(); results.flush(); writer.start();
  writer.send(Op::restart_epoch, now); writer.send(Op::snapshot, now); v = observe("new_writer_snapshot");
  check("replacement_writer_does_not_auto_resume", v.usable() && !consumer->allowed(v, now));
  require(consumer->reconcile(consumer->recovery_ticket(v, now), v, now), "reconcile"); now = stable_period; v = observe("replacement_writer_reconciled");
  check("replacement_writer_recovers_after_checks", consumer->allowed(v, now));

  reset(); v = observe("cached_view_before_expiry");
  check("cached_valid_label_does_not_extend_freshness", !consumer->allowed(v, expiry_age));

  reset();
  writer.send(Op::restart_epoch, now); writer.send(Op::snapshot, now);
  v = space.read(now); write_event(trace, "decision_without_prior_observe", now, v);
  check("decision_observes_new_epoch_itself", !consumer->issue(v, now));

  reset(); writer.send(Op::gap, now); v = observe("first_recovery_gap");
  auto old_ticket = consumer->recovery_ticket(v, now);
  check("cannot_reconcile_invalid_data", !consumer->reconcile(old_ticket, v, now));
  writer.send(Op::snapshot, now); v = observe("first_recovery_snapshot");
  writer.send(Op::gap, 50); now = 50; v = observe("second_recovery_same_epoch");
  writer.send(Op::snapshot, now); v = observe("second_recovery_snapshot");
  check("late_previous_recovery_rejected", !consumer->reconcile(old_ticket, v, now));
  auto current_ticket = consumer->recovery_ticket(v, now);
  Consumer other;
  other.observe(v, now);
  check("ticket_cannot_cross_consumers", !other.reconcile(current_ticket, v, now));
  check("current_recovery_accepted", consumer->reconcile(current_ticket, v, now));
  check("reconciliation_does_not_skip_stability", !consumer->allowed(v, now));
  now = 249; v = observe("before_second_stability_boundary");
  check("new_fault_resets_stability", !consumer->allowed(v, now));
  now = 250; v = observe("second_stability_boundary");
  check("stability_and_reconciliation_complete", consumer->allowed(v, now));

  reset(); writer.send(Op::gap, now); observe("parallel_recovery_gap");
  writer.send(Op::snapshot, now); v = observe("parallel_recovery_snapshot");
  auto parallel_ticket = consumer->recovery_ticket(v, now);
  now = stable_period; v = observe("stable_but_not_reconciled");
  check("stability_alone_does_not_resume", !consumer->allowed(v, now));
  check("late_reconciliation_needs_no_second_stable_period",
        consumer->reconcile(parallel_ticket, v, now) && consumer->allowed(v, now));
  writer.send(Op::restart_epoch, now); writer.send(Op::snapshot, now);
  v = observe("ticket_from_previous_epoch");
  check("old_epoch_reconciliation_rejected", !consumer->reconcile(parallel_ticket, v, now));
  consumer->stop(); consumer->resume();
  check("manual_resume_does_not_bypass_recovery", !consumer->allowed(v, now));

  reset(); writer.send(Op::gap, now); v = observe("repeated_invalid_observation");
  auto repeated_ticket = consumer->recovery_ticket(v, now);
  observe("same_gap_again");
  writer.send(Op::snapshot, now); v = observe("same_recovery_snapshot");
  check("repeated_invalid_observation_keeps_recovery_identity",
        consumer->reconcile(repeated_ticket, v, now));
  consumer.emplace();
  check("recreated_consumer_rejects_old_ticket", !consumer->reconcile(repeated_ticket, v, now));

  // A separate local fixture exercises publication misuse without another writer.
  {
    Space publication;
    check("publish_requires_prepared_draft", !publication.publish(0));
    publication.prepare(0); publication.restart();
    check("old_epoch_draft_rejected", !publication.publish(0));
    publication.replace(0); publication.prepare(0);
    check("complete_draft_published_once", publication.publish(0) && !publication.publish(0));
    publication.prepare(0); experiment::Faults::gap(publication);
    check("ordinary_publish_cannot_clear_gap", !publication.publish(0));
    write_event(trace, "publication_misuse_final_state", 0, publication.read(0));
  }

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
