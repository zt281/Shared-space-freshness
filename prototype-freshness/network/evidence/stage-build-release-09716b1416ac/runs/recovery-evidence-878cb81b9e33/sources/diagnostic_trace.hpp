#pragma once
// Disposable, opt-in measurement sidecar. No wire, journal or shared-layout fields.
// Writers claim disjoint preallocated slots; dump only after all writers have joined.
#include <atomic>
#include <cerrno>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <memory>
#include <stdexcept>
#include <string>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

namespace diagnostic {
struct Event {
  const char* stage = nullptr; // Static string literal only.
  std::uint64_t ns = 0, identity = 0, epoch = 0, sequence = 0, request = 0;
  std::uint64_t a = 0, b = 0, c = 0;
  long tid = 0;
};
struct Buffer {
  std::unique_ptr<Event[]> events;
  std::size_t capacity;
  std::atomic<std::uint64_t> claimed{0}, clock_errors{0};
  std::filesystem::path path;
  explicit Buffer(std::filesystem::path file, std::size_t count)
      : events(new Event[count]{}), capacity(count), path(std::move(file)) {}
};
inline std::unique_ptr<Buffer> buffer;
inline thread_local std::uint64_t request = 0;
inline bool enabled() noexcept { return buffer != nullptr; }
inline std::uint64_t now_ns() noexcept {
  const int saved = errno;
  timespec value{};
  const int result = clock_gettime(CLOCK_MONOTONIC, &value);
  if (result && buffer) ++buffer->clock_errors;
  errno = saved;
  return result ? 0 : static_cast<std::uint64_t>(value.tv_sec) * 1000000000ULL + value.tv_nsec;
}
inline void mark(const char* stage, std::uint64_t identity = 0, std::uint64_t epoch = 0,
                 std::uint64_t sequence = 0, std::uint64_t a = 0, std::uint64_t b = 0,
                 std::uint64_t c = 0) noexcept {
  if (!buffer) return;
  const int saved = errno;
  const auto index = buffer->claimed.fetch_add(1, std::memory_order_relaxed);
  if (index < buffer->capacity) {
    thread_local const long tid = syscall(SYS_gettid);
    buffer->events[index] = {stage, now_ns(), identity, epoch, sequence, request, a, b, c, tid};
  }
  errno = saved;
}
struct Request {
  std::uint64_t previous;
  explicit Request(std::uint64_t value) : previous(request) { request = value; }
  ~Request() { request = previous; }
};
inline void start() {
  const auto* path = std::getenv("TYCHE_PROTOTYPE_TRACE");
  if (!path || !*path) return;
  std::filesystem::path file(path);
  if (!file.is_absolute() || !file.filename().string().starts_with("PROTOTYPE-") ||
      std::filesystem::exists(file))
    throw std::runtime_error("new absolute PROTOTYPE trace path required");
  std::size_t capacity = 65536;
  if (const auto* value = std::getenv("TYCHE_PROTOTYPE_TRACE_CAPACITY")) capacity = std::stoull(value);
  if (!capacity || capacity > 1000000) throw std::runtime_error("bounded diagnostic trace capacity");
  buffer = std::make_unique<Buffer>(file, capacity);
  mark("trace_started");
}
inline void finish() {
  if (!buffer) return;
  mark("trace_finished");
  const auto count = buffer->claimed.load();
  std::ofstream out(buffer->path, std::ios::binary);
  if (!out) throw std::runtime_error("open diagnostic trace");
  for (std::uint64_t i = 0; i < count && i < buffer->capacity; ++i) {
    const auto& e = buffer->events[i];
    if (!e.stage) throw std::runtime_error("diagnostic writer has not finished");
    out << "{\"stage\":\"" << e.stage << "\",\"index\":" << i << ",\"ns\":" << e.ns
        << ",\"pid\":" << getpid() << ",\"tid\":" << e.tid << ",\"identity\":" << e.identity
        << ",\"epoch\":" << e.epoch << ",\"sequence\":" << e.sequence << ",\"request\":" << e.request
        << ",\"a\":" << e.a << ",\"b\":" << e.b << ",\"c\":" << e.c << "}\n";
  }
  out << "{\"stage\":\"trace_summary\",\"clock\":\"CLOCK_MONOTONIC\",\"capacity\":" << buffer->capacity
      << ",\"attempted\":" << count << ",\"overflow\":" << (count > buffer->capacity ? count - buffer->capacity : 0)
      << ",\"clock_errors\":" << buffer->clock_errors << "}\n";
  out.close();
  if (!out) throw std::runtime_error("write diagnostic trace");
  buffer.reset();
}
}
