// PROTOTYPE: each invocation opens its own mapping and journal after exec.
#include "ordered_consumer.hpp"
#include "durable_consumer.hpp"
#include "experiment.hpp"
#include <iomanip>
#include <memory>
#include <optional>
#include <sstream>
#include <sys/mman.h>
#include <sys/resource.h>

namespace {
std::string view_json(const View& view, Tick now) {
  std::ostringstream out;
  write_event(out, "source", now, view); // Preserve every existing observation field.
  auto text = out.str();
  text.pop_back();
  return text;
}
void events_json(const std::vector<Change>& events, Tick now) {
  std::cout << '[';
  bool first = true;
  for (const auto& event : events) {
    if (!first) std::cout << ',';
    first = false;
    const auto& r = event.record;
    View v{r, r.epoch, 0, false, Validity::valid, now - r.verified_time};
    std::cout << "{\"sequence\":" << event.sequence << ",\"seal\":" << event.seal
              << ",\"record\":" << view_json(v, now) << '}';
  }
  std::cout << ']';
}
}

int main(int argc, char** argv) {
  try {
    require(argc == 6 || argc == 9, "usage: independent_worker ROLE NAME JOURNAL IDENTITY ADDRESS [CHECKPOINT CONSUMER_ID START_TICK]");
    const std::string role = argv[1];
    Space::Location location{argv[2], argv[3], std::stoull(argv[4]), std::stoull(argv[5], nullptr, 0)};
    if (role == "unlink") {
      Space::unlink_named(location);
      std::cout << "{\"ok\":true,\"action\":\"unlink\"}" << std::endl;
      return 0;
    }
    if (role == "occupied") {
      const auto length = static_cast<std::size_t>(sysconf(_SC_PAGESIZE));
      void* requested = reinterpret_cast<void*>(location.address);
      void* reservation = mmap(requested, length, PROT_READ | PROT_WRITE,
                               MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0);
      require(reservation != MAP_FAILED && reservation == requested, "reserve collision address");
      auto* sentinel = static_cast<std::uint64_t*>(reservation);
      *sentinel = checksum_salt;
      bool refused = false;
      try { Space attempt(location, Space::Access::reader); }
      catch (const std::system_error& e) { refused = e.code().value() == EEXIST; }
      const bool intact = *sentinel == checksum_salt;
      munmap(reservation, length);
      require(refused && intact, "collision must fail without replacing existing memory");
      std::cout << "{\"ok\":true,\"action\":\"occupied_preserved\"}" << std::endl;
      return 0;
    }
    const bool durable_role = role == "durable" || role == "durable_create";
    require(role == "create" || role == "reader" || role == "publisher" || durable_role, "unknown process role");
    auto space = std::make_unique<Space>(location, role == "create" ? Space::Access::create :
                                                 (role == "reader" || durable_role) ? Space::Access::reader : Space::Access::publisher);
    std::unique_ptr<OrderedConsumer> consumer;
    if (role == "reader") consumer = std::make_unique<OrderedConsumer>(*space, 4, false);
    std::unique_ptr<DurableConsumer> durable;
    if (durable_role) {
      require(argc == 9, "durable reader needs checkpoint and consumer identity");
      durable = std::make_unique<DurableConsumer>(*space, argv[6], std::stoull(argv[7]), role == "durable_create");
    }
    std::optional<Consumer::RecoveryTicket> ticket;

    auto reply = [&](const std::string& action, Tick now, bool ok, const std::string& outcome,
                     const std::vector<Change>& events) {
      const auto info = space->attachment();
      const auto view = space->read(now);
      rusage usage{};
      require(getrusage(RUSAGE_SELF, &usage) == 0, "resource observation");
      std::cout << "{\"ok\":" << (ok ? "true" : "false") << ",\"action\":" << std::quoted(action)
                << ",\"outcome\":" << std::quoted(outcome) << ",\"pid\":" << getpid()
                << ",\"identity\":" << info.identity << ",\"address\":" << info.address
                << ",\"publisher_pid\":" << info.publisher_pid << ",\"publisher_start\":" << info.publisher_start
                << ",\"authority\":" << info.authority << ",\"head\":" << info.head
                << ",\"view\":" << view_json(view, now)
                << ",\"user_cpu_us\":" << usage.ru_utime.tv_sec * 1000000LL + usage.ru_utime.tv_usec
                << ",\"system_cpu_us\":" << usage.ru_stime.tv_sec * 1000000LL + usage.ru_stime.tv_usec
                << ",\"max_rss_kib\":" << usage.ru_maxrss;
      if (consumer || durable) {
        const auto s = durable ? durable->status(now) : consumer->status(now);
        std::cout << ",\"cursor\":" << s.cursor << ",\"processed\":" << s.processed
                  << ",\"backlog\":" << s.backlog << ",\"journal_reads\":" << s.journal_reads
                  << ",\"allowed\":" << (s.allowed ? "true" : "false")
                  << ",\"recovering\":" << (s.recovering ? "true" : "false")
                  << ",\"complete\":" << (s.complete ? "true" : "false")
                  << ",\"alerts\":" << s.alerts << ",\"simulated_cancel_attempts\":" << s.cancellation_attempts
                  << ",\"simulated_cancel_result\":\"" << (s.cancellation_attempts ? "unknown" : "not_attempted") << '"';
      }
      if (durable) {
        const auto& s = durable->saved();
        std::cout << ",\"checkpoint\":{\"revision\":" << s.revision << ",\"cursor\":" << s.cursor
                  << ",\"processed\":" << s.processed << ",\"quantity_sum\":" << s.quantity_sum
                  << ",\"price_sum\":" << s.price_sum << ",\"chain\":" << s.chain
                  << ",\"stopped\":" << s.stopped << ",\"intent_epoch\":" << s.intent_epoch
                  << ",\"intent_expires\":" << s.intent_expires << ",\"intent_outcome\":" << s.intent_outcome
                  << ",\"error\":" << std::quoted(durable->error()) << '}';
      }
      std::cout << ",\"events\":";
      events_json(events, now);
      std::cout << '}' << std::endl;
    };
    reply("attached", argc == 9 ? std::stoll(argv[8]) : 0, true, "", {});
    std::string line;
    while (std::getline(std::cin, line)) {
      std::istringstream input(line);
      std::string action;
      Tick now = 0;
      std::size_t budget = 0;
      require(static_cast<bool>(input >> action >> now >> budget), "invalid control command");
      if (action == "quit") return 0;
      require(space != nullptr, "mapping was released; only process exit is permitted");
      if (action == "exit_abrupt") _exit(77); // Controlled death outside the publication critical section.
      if (action == "release") {
        reply(action, now, true, "closing_mapping_while_process_remains_alive", {});
        consumer.reset(); durable.reset(); space.reset();
        // A separate acknowledgement proves descriptors were actually closed.
        std::cout << "{\"ok\":true,\"action\":\"released\",\"pid\":" << getpid() << '}' << std::endl;
        continue;
      }
      bool ok = true;
      std::string outcome;
      std::vector<Change> events;
      const auto before = space->attachment().head;
      try {
        if (action == "prepare") space->prepare(now);
        else if (action == "publish") ok = space->publish(now);
        else if (action == "replace") space->replace(now);
        else if (action == "verify") space->verify(now);
        else if (action == "heartbeat") space->heartbeat();
        else if (action == "replay") space->replay(now);
        else if (action == "restart") space->restart();
        else if (action == "arm_publication_crash") experiment::Faults::publication_crash(*space, static_cast<int>(budget));
        else if (action == "publish_reply_crash") { space->publish(now); _exit(77); }
        else if (action == "query") {
          require(budget > 0, "query sequence must be positive");
          const auto result = space->read_after(budget - 1, 1, now);
          ok = result.complete;
          events = result.events;
        }
        else if (action == "inspect") {}
        else if (durable) {
          if (action == "consume") ok = durable->consume(now, budget, events);
          else if (action == "capture") ticket = durable->recovery_ticket(now);
          else if (action == "reconcile") ok = ticket && durable->reconcile(*ticket, now);
          else if (action == "stop") durable->stop();
          else if (action == "resume") durable->resume();
          else if (action == "issue") ok = durable->issue(now);
          else if (action == "execute") outcome = durable->execute(now);
          else if (action == "arm_checkpoint_crash") experiment::Faults::checkpoint_crash(*durable, static_cast<int>(budget));
          else throw std::runtime_error("unknown durable consumer action");
        }
        else {
          require(consumer != nullptr, "consumer operation requires reader");
          if (action == "consume") ok = consumer->consume(now, budget, [&](const Change& e) {
            events.push_back(e); return true;
          });
          else if (action == "capture") ticket = consumer->recovery_ticket(now);
          else if (action == "reconcile") ok = ticket && consumer->reconcile(*ticket, now);
          else if (action == "stop") consumer->stop();
          else if (action == "resume") consumer->resume();
          else if (action == "issue") ok = consumer->issue(now);
          else if (action == "execute") outcome = consumer->execute(now);
          else throw std::runtime_error("unknown control action");
        }
        if (role == "publisher" && space->attachment().head > before)
          events = space->read_after(before, Space::buffer_capacity, now).events;
      } catch (const std::exception& e) { ok = false; outcome = e.what(); }
      reply(action, now, ok, outcome, events);
    }
    return 0;
  } catch (const std::exception& e) {
    std::cout << "{\"ok\":false,\"action\":\"startup_failed\",\"error\":" << std::quoted(e.what()) << '}' << std::endl;
    return 2;
  }
}
