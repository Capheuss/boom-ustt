#!/usr/bin/env bash
# Cycles and IPC for one BOOM config in Verilator: riscv-tests benchmarks (Dhrystone included) and CoreMark. Appends one row per benchmark to logs/perf/raw.csv; scripts/perf/report.py normalizes it to the baseline and plots it. Run one config at a time: concurrent runs fight over the sbt lock.
#
#   scripts/perf/run.sh MediumBoomV3Config
#
# Env: JOBS (default 16), CM_ITER CoreMark iterations (default 3, recorded in the iterations column), T_BUILD T_BMARK T_CM per-step timeout in s, RAW_CSV (default logs/perf/raw.csv)
#
# Counters are mcycle/minstret over each benchmark's timed region. status is PASS, FAIL (run failed, timed out or CoreMark CRC wrong) or NO_COUNTERS (ran, but prints no counters: pmp, mm, mt-* on one core; CoreMark without counters is FAIL). Exit 1 on any FAIL.

set -u

here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
config=${1:?usage: scripts/perf/run.sh <CONFIG>}
[ "${USTT_ROOT:-}" = "$root" ] || exec "$root/ustt" "$0" "$@"

commit=$(git -C "$root" rev-parse --short HEAD)
[ -n "$(git -C "$root" status --porcelain --untracked-files=no)" ] && commit="$commit (dirty)"
logdir=$root/logs/perf/$config-$(date +%Y%m%d-%H%M%S)
raw=${RAW_CSV:-$root/logs/perf/raw.csv}
simdir=$root/sims/verilator
outdir=$simdir/output/chipyard.harness.TestHarness.$config
jobs=${JOBS:-16}
cm_iter=${CM_ITER:-3}
mkdir -p "$logdir"
header="config,commit,bench,status,cycles,instret,ipc,log,iterations"
[ -s "$raw" ] || echo "$header" >"$raw"
[ "$(head -1 "$raw")" = "$header" ] || { echo "$raw has an old header; move it aside"; exit 1; }

fails=0
row() { # bench status log [iterations]
  local c i ipc=""
  c=$(sed -n 's/^mcycle = \([0-9]*\)$/\1/p' "$3" 2>/dev/null | tail -1)
  i=$(sed -n 's/^minstret = \([0-9]*\)$/\1/p' "$3" 2>/dev/null | tail -1)
  local st=$2
  [ "$st" = PASS ] && { [ -n "$c" ] && [ -n "$i" ] || st=NO_COUNTERS; }
  [ "$st" = NO_COUNTERS ] && [ "$1" = coremark ] && st=FAIL # the counter hook stopped working
  [ "$st" = PASS ] && ipc=$(awk -v i="$i" -v c="$c" 'BEGIN { printf "%.4f", i / c }')
  [ "$st" = FAIL ] && fails=$((fails + 1))
  [ "$st" = PASS ] || { c=""; i=""; }
  echo "$config,$commit,$1,$st,$c,$i,$ipc,$3,${4:-}" >>"$raw"
  printf '%-12s %-11s %10s %10s %7s\n' "$1" "$st" "$c" "$i" "$ipc"
}

if ! timeout "${T_BUILD:-5400}" make -C "$simdir" CONFIG="$config" -j"$jobs" >"$logdir/build.log" 2>&1; then
  echo "build failed: $logdir/build.log"; exit 1
fi

# riscv-tests benchmarks. Status files are rewritten every run (FORCE), so they list exactly this run's benchmarks.
rm -rf "$outdir/run-fast-status/bmark"
timeout "${T_BMARK:-3600}" make -C "$simdir" CONFIG="$config" -j"$jobs" run-bmark-tests-fast >"$logdir/bmark.log" 2>&1
bmark_rc=$?
[ $bmark_rc -eq 124 ] && echo "riscv-tests benchmarks timed out after ${T_BMARK:-3600}s" >>"$logdir/bmark.log"

printf '%-12s %-11s %10s %10s %7s\n' BENCH STATUS CYCLES INSTRET IPC
n=0
for f in "$outdir"/run-fast-status/bmark/*.status; do
  [ -e "$f" ] || continue
  b=$(basename "$f" .status); n=$((n + 1))
  cp "$outdir/$b.log" "$logdir/$b.log" 2>/dev/null
  row "$b" "$(cut -f1 "$f")" "$logdir/$b.log"
done
# A timeout or a benchmark that never started leaves no .status file, so a failed make is a FAIL of its own.
[ "$n" -gt 0 ] && [ $bmark_rc -eq 0 ] || row riscv-tests FAIL "$logdir/bmark.log"

# CoreMark, built out of tree with the counter hook in hooks/valgrind/callgrind.h.
cm=$logdir/coremark.log
if make -s -C "$root/software/coremark/riscv-coremark/coremark" PORT_DIR=../riscv64-baremetal compile \
     ITERATIONS="$cm_iter" OPATH="$logdir/" XCFLAGS="-DCALLGRIND_RUN=1 -I$here/hooks" >"$logdir/coremark-build.log" 2>&1 &&
   timeout "${T_CM:-3600}" make -C "$simdir" CONFIG="$config" run-binary-fast BINARY="$logdir/coremark.bare.riscv" >"$cm" 2>&1 &&
   # Known CRCs of CoreMark's 2K performance run; crcfinal depends on the iteration count.
   grep -q 'crclist *: 0xe714' "$cm" && grep -q 'crcmatrix *: 0x1fd7' "$cm" && grep -q 'crcstate *: 0x8e3a' "$cm"; then
  row coremark PASS "$cm" "$cm_iter"
else
  row coremark FAIL "$cm" "$cm_iter"
fi

echo "config $config, start commit $commit, CoreMark iterations $cm_iter, logs $logdir, rows appended to $raw"
[ "$fails" -eq 0 ]
