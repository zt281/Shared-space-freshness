#pragma once
// Disposable, version-pinned wire experiment. Never send native Change bytes.
#include "space.hpp"
#include <array>
#include <algorithm>
#include <cstring>
#include <span>
#include <limits>

namespace quic_demo {
using Words = std::vector<std::uint64_t>;
using Bytes = std::vector<std::uint8_t>;
constexpr std::uint64_t protocol = 0x5459515500000001ULL;
constexpr std::size_t max_words = 32, record_words = 13;
inline Bytes encode(const Words& words) {
  require(!words.empty() && words.size() <= max_words, "wire frame bound");
  const auto n = static_cast<std::uint32_t>(words.size() * 8);
  Bytes out{static_cast<std::uint8_t>(n >> 24), static_cast<std::uint8_t>(n >> 16),
            static_cast<std::uint8_t>(n >> 8), static_cast<std::uint8_t>(n)};
  for (auto value : words) for (int shift = 56; shift >= 0; shift -= 8)
    out.push_back(static_cast<std::uint8_t>(value >> shift));
  return out;
}
inline Words decode(std::span<const std::uint8_t> bytes) {
  require(bytes.size() % 8 == 0 && bytes.size() <= max_words * 8, "wire word length");
  Words words;
  for (std::size_t i = 0; i < bytes.size(); i += 8) {
    std::uint64_t word = 0;
    for (std::size_t j = 0; j < 8; ++j) word = (word << 8) | bytes[i+j];
    words.push_back(word);
  }
  return words;
}
inline Words record_words_of(const Change& e) {
  const auto& r = e.record;
  return {e.sequence,r.epoch,r.version,r.proof,static_cast<std::uint64_t>(r.value_time),
          static_cast<std::uint64_t>(r.verified_time),static_cast<std::uint64_t>(r.received_time),
          r.price,r.quantity,r.checksum,r.gap,r.time_known,e.seal};
}
inline Change record_from(const Words& w, std::size_t i) {
  require(w.size() == i + record_words && w[i+10] <= 1 && w[i+11] <= 1, "wire record length/bool");
  require(w[i] > 0 && w[i+1] > 0 && w[i+2] > 0, "wire identity/version");
  for (auto k : {4,5,6}) require(w[i+k] <= static_cast<std::uint64_t>(std::numeric_limits<Tick>::max()),
                                "wire timestamp range");
  Record r{w[i+1],w[i+2],w[i+3],static_cast<Tick>(w[i+4]),static_cast<Tick>(w[i+5]),
           static_cast<Tick>(w[i+6]),w[i+7],w[i+8],w[i+9],w[i+10]!=0,w[i+11]!=0};
  Change e{w[i],r,w[i+12]};
  require(r.checksum == checksum(r) && Space::proposal(e.sequence,r).seal == e.seal,
          "wire payload seal/checksum");
  return e;
}
// A stream is bytes, not callback-sized messages. At most one frame is retained.
class Framer {
  std::array<std::uint8_t, 4 + max_words*8> bytes{};
  std::size_t used = 0, needed = 4;
public:
  std::size_t pending() const { return used; }
  template<class Accept> void feed(std::span<const std::uint8_t> input, Accept accept) {
    while (!input.empty()) {
      auto n = std::min(input.size(), needed-used);
      std::memcpy(bytes.data()+used,input.data(),n); used += n; input = input.subspan(n);
      if (used != needed) continue;
      if (needed == 4) {
        const auto size = (std::uint32_t(bytes[0])<<24)|(std::uint32_t(bytes[1])<<16)|
                          (std::uint32_t(bytes[2])<<8)|bytes[3];
        require(size && size%8==0 && size <= max_words*8, "invalid/oversize wire frame");
        needed = 4+size;
      } else {
        auto words = decode(std::span(bytes.data()+4,needed-4));
        used = 0; needed = 4;
        accept(words);
      }
    }
  }
};
}
