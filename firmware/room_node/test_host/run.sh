#!/usr/bin/env bash
# Compile and run the host tests (no ESP-IDF needed): firmware/room_node/test_host/run.sh
set -eu
cd "$(dirname "$0")"
for t in scd40 ds18b20 toggles; do
    out="${TMPDIR:-/tmp}/room_node_test_$t"
    cc -std=c11 -Wall -Wextra -Werror -I stubs "test_$t.c" -o "$out" -lm
    "$out"
done
