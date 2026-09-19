#!/usr/bin/env bash
set -euo pipefail
prototype_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cmake -S "$prototype_dir" -B "$prototype_dir/build" -DCMAKE_BUILD_TYPE=Debug
cmake --build "$prototype_dir/build" --parallel 2
ctest --test-dir "$prototype_dir/build" --output-on-failure --verbose
