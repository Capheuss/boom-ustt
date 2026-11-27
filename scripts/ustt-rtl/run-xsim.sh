#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
    echo "Usage: run-xsim.sh <prepared-test-directory>" >&2
    exit 1
fi
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
work=$(cd "$1" && pwd)
src="${USTT_RTL_SRC:-$repo/reference/uSTT/rtl/src}"
src=$(cd "$src" && pwd)
cd "$work"

sources=()
for name in reg pe eq_comp rename younger stt_control stt_og stt_age; do
    sources+=("$src/$name.v")
done

python3 - "$repo" "$src" <<'PY_SIM_METADATA'
import datetime
import hashlib
import json
import subprocess
import sys
from pathlib import Path

repo, source = map(Path, sys.argv[1:])
manifest = Path("simulation-metadata.json")
if manifest.exists():
    raise SystemExit("Simulation metadata already exists; prepare a fresh test directory.")

def git(*args):
    return subprocess.check_output(
        ["git", "-C", str(repo), *args], text=True
    ).strip()

files = [
    source / (name + ".v")
    for name in ("reg", "pe", "eq_comp", "rename", "younger",
                 "stt_control", "stt_og", "stt_age")
]
files += [
    Path("testbench.sv"), Path("generator.py"), Path("test-metadata.json"),
    repo / "scripts/ustt-rtl/run-xsim.sh",
    repo / "scripts/ustt-rtl/prepare-test.py",
]
files += sorted(Path(".").glob("*.input"))
record = {
    "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "source_directory": str(source),
    "repository_commit": git("rev-parse", "HEAD"),
    "working_tree_status": git("status", "--short"),
    "prepared_test": json.loads(Path("test-metadata.json").read_text()),
    "files_sha256": {
        str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in files
    },
}
with manifest.open("x") as stream:
    json.dump(record, stream, indent=2)
    stream.write("\n")
PY_SIM_METADATA

echo "Compiling reference RTL..."
if ! timeout 300s xvlog --sv "${sources[@]}" testbench.sv > xvlog.log 2>&1; then
    tail -n 60 xvlog.log
    exit 1
fi

echo "Elaborating testbench..."
if ! timeout 300s xelab stt_testbench --timescale 1ns/1ps --mt off -s stt_snapshot > xelab.log 2>&1; then
    tail -n 60 xelab.log
    exit 1
fi

echo "Running simulation..."
if ! timeout 300s xsim stt_snapshot -runall -onfinish quit > xsim.log 2>&1; then
    tail -n 60 xsim.log
    exit 1
fi

if grep -Fq '[FAIL]' xsim.log || ! grep -Fq 'ALL TESTS PASSED!' xsim.log; then
    tail -n 60 xsim.log
    echo "FAIL: simulation did not report successful completion." >&2
    exit 1
fi

python3 - <<'PY'
import json
from pathlib import Path

expected = json.loads(Path("test-metadata.json").read_text())["vector_count"]
actual = Path("xsim.log").read_text().count("[PASS]")
if actual != expected:
    raise SystemExit(f"FAIL: expected {expected} passing cases, observed {actual}")
print(f"PASS: {actual}/{expected} reference test cases.")
PY
