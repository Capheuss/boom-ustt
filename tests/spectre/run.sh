#!/usr/bin/env bash
# Build and run one Spectre PoC on a Verilator BOOM config.
#
#   ./run.sh [CONFIG] [v1|v2|rsb]        default: SmallBoomV3Config v1
#   DRAMSIM=1 ./run.sh ...               official numbers (4x slower)
#   TIMEOUT=600 MAX_CYCLES=... ./run.sh
#
# Exit status: 0 = no leak (mitigation held), 1 = leak, 2 = no result.

set -u

here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
config=${1:-SmallBoomV3Config}
attack=${2:-v1}
sim=$root/sims/verilator/simulator-chipyard.harness-$config
bin=$here/$attack.riscv

if [ ! -x "$sim" ]; then
  echo "missing $sim" >&2
  echo "build it: ./ustt make -C sims/verilator CONFIG=$config -j16" >&2
  exit 2
fi

if ! (cd "$root" && ./ustt make -s -B -C tests/spectre "$attack.riscv"); then
  exit 2
fi

dram_flags=""
if [ -n "${DRAMSIM:-}" ]; then
  dram_flags="+dramsim +dramsim_ini_dir=$root/generators/testchipip/src/main/resources/dramsim2_ini"
fi

sig=$(mktemp /tmp/spectre-sig.XXXXXX)
log=$(mktemp /tmp/spectre-log.XXXXXX)

# shellcheck disable=SC2086
timeout "${TIMEOUT:-1800}" "$sim" +permissive +verbose \
  +max-cycles="${MAX_CYCLES:-400000000}" +signature="$sig" $dram_flags \
  +permissive-off "$bin" >"$log" 2>&1
simrc=$?

simcycles=$(grep -o 'Completed after *[0-9]* simulation cycles' "$log" |
            grep -o '[0-9]*' || true)

python3 - "$sig" <<'PY'
import struct
import sys

MAGIC = 0x53504543
EXPECTED = b'!"#ThisIsTheBabyBoomerTest'

try:
    text = open(sys.argv[1]).read()
except OSError:
    print("RESULT: NO_SIGNATURE")
    sys.exit(2)
data = b"".join(bytes.fromhex(line)[::-1] for line in text.split())
if len(data) < 128:
    print("RESULT: NO_SIGNATURE")
    sys.exit(2)

magic, mask, cycles = struct.unpack_from("<IIQ", data, 0)
if magic != MAGIC:
    print("RESULT: NO_SIGNATURE (magic=%#x)" % magic)
    sys.exit(2)

recovered = data[16:42]
alt = data[42:68]
count0 = data[68:94]
count1 = data[94:120]
good = sum(a == b for a, b in zip(recovered, EXPECTED))

print("recovered: %r" % recovered)
print("expected : %r" % EXPECTED)
print("alt      : %r" % alt)
print("count0   : %s" % list(count0))
print("count1   : %s" % list(count1))
print("cycles   : %d (rdcycle)" % cycles)
print("mask     : %#010x (%d/%d)" % (mask, good, len(EXPECTED)))
print("RESULT: %s" % ("LEAK" if good == len(EXPECTED) else "NO_LEAK"))
sys.exit(1 if good == len(EXPECTED) else 0)
PY
result=$?

echo "sim      : $config $attack (exit $simrc${simcycles:+, $simcycles cycles})"
echo "wall     : ${SECONDS}s"
echo "SPECTRE_RESULT attack=$attack config=$config result=$(
  [ "$result" -eq 0 ] && echo NO_LEAK || { [ "$result" -eq 1 ] && echo LEAK || echo ERROR; }
)${simcycles:+ simcycles=$simcycles}"
echo "log      : $log"

exit "$result"
