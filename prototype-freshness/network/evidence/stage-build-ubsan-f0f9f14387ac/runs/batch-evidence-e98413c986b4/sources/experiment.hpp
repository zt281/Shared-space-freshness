#pragma once
#include "space.hpp"
#include "faults.hpp"
#include <cerrno>
#include <csignal>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <thread>
#include <chrono>
#include <utility>
#include <sys/wait.h>
#include <unistd.h>

enum class Op { reset, draft, publish, replay, heartbeat, verify, gap,
                unknown_time, snapshot, restart_epoch, stress, crash, quit, rejected_publish };
struct Message { Op op; Tick now; std::uint64_t count = 0; };
inline void transfer(int fd, void* data, std::size_t size, bool writing) {
  auto* p = static_cast<char*>(data);
  while (size) {
    ssize_t n = writing ? write(fd, p, size) : read(fd, p, size);
    if (n < 0 && errno == EINTR) continue;
    require(n > 0, "prototype control pipe closed or failed");
    size -= static_cast<std::size_t>(n);
    p += n;
  }
}
inline void write_event(std::ostream& out, const char* event, Tick now, const View& v) {
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
  Space& space;
  std::filesystem::path evidence;
  pid_t pid = -1;
  int request = -1, response = -1;
  void worker(int in, int out) {
    std::ofstream log(evidence / "publisher.jsonl", std::ios::app);
    require(log.good(), "publisher evidence file");
    for (;;) {
      Message m{};
      transfer(in, &m, sizeof(m), false);
      if (m.op == Op::quit) return;
      if (m.op == Op::crash) experiment::Faults::crash(space);
      if (m.op == Op::stress) {
        for (std::uint64_t i = 0; i < m.count; ++i) {
          space.prepare(m.now);
          require(space.publish(m.now), "stress publication rejected");
          write_event(log, "complete_publish", m.now, space.read(m.now));
          if (i % 100 == 0) std::this_thread::sleep_for(std::chrono::microseconds(100));
        }
      } else {
        switch (m.op) {
          case Op::reset: experiment::Faults::reset(space, m.now); break;
          case Op::draft: space.prepare(m.now); break;
          case Op::publish: require(space.publish(m.now), "publication rejected"); break;
          case Op::rejected_publish: require(!space.publish(m.now), "expected rejected publication"); break;
          case Op::replay: space.replay(m.now); break;
          case Op::heartbeat: space.heartbeat(); break;
          case Op::verify: space.verify(m.now); break;
          case Op::gap: experiment::Faults::gap(space); break;
          case Op::unknown_time: experiment::Faults::unknown_time(space); break;
          case Op::snapshot: space.replace(m.now); break;
          case Op::restart_epoch: space.restart(); break;
          default: throw std::runtime_error("unexpected experiment operation");
        }
      }
      write_event(log, "publisher_action", m.now, space.read(m.now));
      log.flush();
      require(log.good(), "publisher evidence write failed");
      int ack = 1;
      transfer(out, &ack, sizeof(ack), true);
    }
  }
public:
  Publisher(Space& s, std::filesystem::path path) : space(s), evidence(std::move(path)) { start(); }
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
