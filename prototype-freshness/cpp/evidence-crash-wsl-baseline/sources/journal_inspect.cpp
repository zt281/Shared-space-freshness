// Read-only inspection of the compiler's local PROTOTYPE Change layout.
#include "space.hpp"
#include <fstream>
#include <iostream>

int main(int argc, char** argv) {
  try {
    require(argc == 2, "usage: journal_inspect PROTOTYPE-journal");
    std::ifstream file(argv[1], std::ios::binary);
    require(file.good(), "open PROTOTYPE journal");
    Change event{};
    while (file.read(reinterpret_cast<char*>(&event), sizeof(event))) {
      const auto& r = event.record;
      std::cout << "{\"sequence\":" << event.sequence << ",\"seal\":" << event.seal
                << ",\"epoch\":" << r.epoch << ",\"version\":" << r.version
                << ",\"proof\":" << r.proof << ",\"value_ms\":" << r.value_time
                << ",\"verified_ms\":" << r.verified_time << ",\"received_ms\":" << r.received_time
                << ",\"price\":" << r.price << ",\"quantity\":" << r.quantity
                << ",\"checksum\":" << r.checksum << ",\"gap\":" << (r.gap ? "true" : "false")
                << ",\"time_known\":" << (r.time_known ? "true" : "false")
                << ",\"valid\":" << (event.seal == seal(event) && r.checksum == checksum(r) ? "true" : "false")
                << ",\"record_bytes\":" << sizeof(event) << "}\n";
    }
    require(file.eof() && file.gcount() == 0, "partial or unreadable journal record");
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 2;
  }
}
