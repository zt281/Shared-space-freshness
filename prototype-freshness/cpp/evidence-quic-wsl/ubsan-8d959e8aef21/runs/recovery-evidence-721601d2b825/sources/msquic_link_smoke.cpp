// Compile/link evidence only. This task does not execute a QUIC connection.
#include <msquic.h>
int main() {
  const QUIC_API_TABLE* api = nullptr;
  const auto status = MsQuicOpen2(&api);
  if (QUIC_FAILED(status)) return 1;
  MsQuicClose(api);
  return 0;
}
