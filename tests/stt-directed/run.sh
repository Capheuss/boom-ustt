#!/usr/bin/env bash
# [boom-ustt] Run one full-core STT directed case and check that the transmitter waited.
#
#   ./run.sh [CONFIG] [1|2|3a|3b|4]       default: MediumBoomV3STTConfig 1
#   TIMEOUT=1800 MAX_CYCLES=... ./run.sh ...
#
# The simulator runs with +stt_trace=1, so the issue queues print one line per cycle a
# ready transmitter is held by the STT gate and one line per transmitter issue.
# The verdict combines the program's own result check, the simulator exit status
# (any assertion stops the simulation), and the trace evidence for each case (README.md).
#
# Prints one line:  STT_DIRECTED case=<c> config=<cfg> result=PASS|FAIL ...
# Exit status: 0 PASS, 1 FAIL, 2 ERROR (build, timeout, missing simulator).

set -u

here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
config=${1:-MediumBoomV3STTConfig}
case_id=${2:-1}
sim=${SIM:-$root/sims/verilator/simulator-chipyard.harness-$config}
bin=$here/case$case_id.riscv

error() {
  echo "STT_DIRECTED case=$case_id config=$config result=ERROR reason=$1"
  exit 2
}

[ -x "$sim" ] || error no_simulator
(cd "$root" && ./ustt make -s -B -C tests/stt-directed "case$case_id.riscv" >/dev/null 2>&1) ||
  error build_failed
[ -x "$bin" ] || error no_binary

out_dir=${LOG_DIR:-$root/logs/stt-directed}
mkdir -p "$out_dir"
log=$out_dir/case$case_id-$config.log
syms=$out_dir/case$case_id-$config.syms

(cd "$root" && ./ustt riscv64-unknown-elf-nm "$bin") >"$syms" || error nm_failed

timeout "${TIMEOUT:-1800}" "$root/ustt" "$sim" +permissive +verbose +stt_trace=1 \
  +max-cycles="${MAX_CYCLES:-50000000}" +permissive-off "$bin" >"$log" 2>&1
simrc=$?
[ "$simrc" -eq 124 ] && error timeout

python3 - "$case_id" "$config" "$simrc" "$log" "$syms" <<'PY'
import re
import sys

case_id, config, simrc, log, syms = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5]

sym = {}
for line in open(syms):
    parts = line.split()
    if len(parts) == 3:
        sym[parts[2]] = int(parts[0], 16)

TRACE = re.compile(r'\[stt-trace\] cycle=\s*(\d+) iq=(\d+) slot=\s*(\d+) (hold|issue) pc=0x([0-9a-f]+) '
                   r'rob=\s*(\d+) yrot=(\d):\s*(\d+) vp=(\d):\s*(\d+) br_tag=\s*(\d+)')
events, program, asserts, probe = [], [], 0, None
for line in open(log, errors='replace'):
    m = TRACE.search(line)
    if m:
        c, iq, slot, kind, pc, rob, yv, yb, vv, vb, tag = m.groups()
        events.append(dict(cycle=int(c), kind=kind, pc=int(pc, 16), rob=int(rob), tag=int(tag)))
        continue
    if line.startswith('STT_'):
        program.append(line.strip())
        if line.startswith('STT_PROBE'):
            probe = dict(kv.split('=') for kv in line.split()[1:])
    if '[boom-ustt]' in line or 'Assertion failed' in line:
        asserts += 1

def at(name):
    return [e for e in events if e['pc'] == sym[name]]

def episodes(name):
    """Group a transmitter's trace into stays in the issue queue: holds, then an issue or not."""
    eps, cur = [], None
    for e in at(name):
        if cur is None or cur["issued"] or e["rob"] != cur["rob"] or e["cycle"] - cur["last"] > 100:
            cur = dict(rob=e['rob'], first=e['cycle'], last=e['cycle'], holds=0, issued=False, issue=None)
            eps.append(cur)
        cur['last'] = e['cycle']
        if e['kind'] == 'hold':
            cur['holds'] += 1
        else:
            cur['issued'], cur['issue'] = True, e['cycle']
    return eps

def last_issue_before(name, cycle):
    prior = [e for e in at(name) if e['kind'] == 'issue' and e['cycle'] <= cycle]
    return prior[-1] if prior else None

program_pass = any(l == 'STT_CASE result=PASS' for l in program)
checks, fields = [], {}

def need(ok, what):
    checks.append((ok, what))

if case_id == '1':
    same_row = 0
    for i in range(4):
        for n, ep in enumerate(episodes(f'stt_c1_tx{i}')):
            br = last_issue_before(f'stt_c1_br{i}', ep['last'])
            rt = last_issue_before(f'stt_c1_root{i}', ep['last'])
            row = br is not None and rt is not None and br['rob'] % 2 == 0 and rt['rob'] == br['rob'] + 1
            print(f"copy {i} stay {n}: T held {ep['holds']} cycles, issued at {ep['issue']}; "
                  f"B issued at {br and br['cycle']} rob {br and br['rob']}; "
                  f"R rob {rt and rt['rob']}; B and R in one dispatch row: {row}")
            # Every copy: T issues only after B. Whether T is ready before B resolves depends on
            # how far ahead the divider is, so the hold itself is required of the warm copies
            # where B and R share a dispatch row, which is the case under test.
            # A stay can also end in a squash (a younger-path mispredict); it then never fired.
            need(not ep['issued'] or (br is not None and ep['issue'] > br['cycle']),
                 f'copy {i} stay {n}: T issued only after B (or was squashed)')
            if n > 0 and row and ep['holds'] > 0:
                same_row += 1
    need(same_row > 0, 'warm pass: B and R in one dispatch row, T held, then issued after B')
    fields['same_row_held'] = same_row
    fields['episodes'] = sum(len(episodes(f'stt_c1_tx{i}')) for i in range(4))
elif case_id == '2':
    eps = episodes('stt_c2_tx')
    br = at('stt_c2_br')
    for ep in eps:
        print(f"T held {ep['holds']} cycles from {ep['first']} to {ep['last']}, issued: {ep['issued']}")
    print(f"B issued at {[e['cycle'] for e in br if e['kind'] == 'issue']}")
    # The training calls run T on the correct path; the last stay is the mispredicted call.
    last = eps[-1] if eps else None
    need(len(eps) >= 2 and all(e['issued'] for e in eps[:-1]), 'training calls: T issued on the correct path')
    need(last is not None and last['holds'] > 0, 'wrong-path T was ready and held')
    need(last is not None and not last['issued'], 'wrong-path T never issued')
    if probe is not None:
        p, cold, hot = int(probe['probe']), int(probe['cold']), int(probe['hot'])
        # The reference line nothing touched must miss, or the eviction failed and the probe
        # says nothing.
        evicted = cold - hot >= 15
        miss_like = evicted and p - hot > (cold - hot) // 2
        print(f"probe line latency {p} cycles (untouched line {cold}, hit {hot}): "
              f"{'miss' if miss_like else 'HIT' if evicted else 'eviction failed'}")
        need(evicted, 'eviction worked: the untouched reference line misses')
        need(miss_like, 'probe line was not brought in by the wrong path')
        fields.update(probe=p, cold=cold, hot=hot)
    else:
        need(False, 'probe latency printed')
    fields['wrong_path_held_cycles'] = last['holds'] if last else 0
elif case_id in ('3a', '3b'):
    eps = episodes(f'stt_c{case_id}_tx')
    for ep in eps:
        print(f"T held {ep['holds']} cycles from {ep['first']} to {ep['last']}, issued: {ep['issued']}")
    killed = [e for e in eps if not e['issued'] and e['holds'] > 0]
    issued = [e for e in eps if e['issued'] and e['holds'] > 0]
    # Three passes; the first may run with cold caches, so at least the two warm ones must show it.
    need(len(killed) >= 2, 'T was held when the exception flushed it (two warm passes)')
    need(len(issued) >= 2, 'T was held again after the handler, then issued (two warm passes)')
    fields.update(killed=len(killed), issued=len(issued))
elif case_id == '5':
    eps = episodes('stt_c5_tx')
    for n, ep in enumerate(eps):
        br = last_issue_before('stt_c5_br', ep['last'])
        rt = last_issue_before('stt_c5_root', ep['last'])
        print(f"pass {n}: R issued at {rt and rt['cycle']}, B issued at {br and br['cycle']}, "
              f"T issued at {ep['issue']} (held {ep['holds']} cycles)")
        if n > 0:
            need(ep['issued'] and br is not None and ep['issue'] - br['cycle'] > 100,
                 f'pass {n}: U and T still queued well after B resolved and R retired')
    need(len(eps) >= 3, 'three passes traced')
elif case_id == '4':
    eps = episodes('stt_c4_tx')
    loops = [e for e in at('stt_c4_loop') if e['kind'] == 'issue']
    for n, ep in enumerate(eps):
        br = last_issue_before('stt_c4_br', ep['last'])
        judged = n > 0  # pass 0 runs with cold caches and predictors
        inside = [e for e in loops if ep['first'] <= e['cycle'] <= (ep['issue'] or ep['last'])]
        tags = {}
        for e in inside:
            tags[e['tag']] = tags.get(e['tag'], 0) + 1
        reuse = max(tags.values(), default=0)
        print(f"pass {n}: T held {ep['holds']} cycles, issued at {ep['issue']}; B issued at {br and br['cycle']} "
              f"tag {br and br['tag']}; {len(inside)} loop branches resolved while T was held, "
              f"{len(tags)} distinct tags, most-reused tag {reuse} times; B's tag among them: "
              f"{br is not None and br['tag'] in tags}")
        if not judged:
            continue
        need(ep['holds'] > 0 and ep['issued'], f'pass {n}: T held, then issued')
        need(br is not None and ep['issue'] > br['cycle'], f'pass {n}: T issued after B')
        need(len(inside) > 12 and reuse >= 2, f'pass {n}: branch tags reused while T was held')
        need(br is not None and br['tag'] not in tags, f"pass {n}: B's tag not reallocated while B is unresolved")
    need(len(eps) >= 3, 'three passes traced')
else:
    print('unknown case')
    sys.exit(2)

need(simrc == 0, 'simulator exit status 0')
need(program_pass, 'program result check')
need(asserts == 0, 'no assertion fired')
for line in program:
    print(line)
for ok, what in checks:
    print(f"  [{'ok' if ok else 'FAIL'}] {what}")
result = 'PASS' if all(ok for ok, _ in checks) else 'FAIL'
extra = ''.join(f' {k}={v}' for k, v in fields.items())
print(f"STT_DIRECTED case={case_id} config={config} result={result} simrc={simrc} assertions={asserts}{extra}")
print(f"log      : {log}")
sys.exit(0 if result == 'PASS' else 1)
PY
