// PROTOTYPE diagnosis only: interpose on this experiment's publisher process.
#include <cstdlib>
#include <dlfcn.h>
#include <unistd.h>

extern "C" int fdatasync(int fd) {
  using Sync = int (*)(int);
  const auto real_sync = reinterpret_cast<Sync>(dlsym(RTLD_NEXT, "fdatasync"));
  if (!real_sync) _exit(78);
  const int result = real_sync(fd);
  static unsigned completed = 0;
  const char* target = std::getenv("TYCHE_PROTOTYPE_CRASH_ON_SYNC");
  if (result == 0 && target && ++completed == std::strtoul(target, nullptr, 10)) {
    constexpr char message[] = "PROTOTYPE: fdatasync succeeded; exit before returning to append\n";
    const auto ignored = write(STDERR_FILENO, message, sizeof(message) - 1);
    (void)ignored;
    _exit(77);
  }
  return result;
}
