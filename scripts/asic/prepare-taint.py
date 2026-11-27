#!/usr/bin/env python3
"""Snapshot standalone Chisel taint RTL for Genus synthesis."""
import argparse
import hashlib
import json
import re
import shlex
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--profile", choices=["medium", "mega"], required=True)
parser.add_argument("--mode", choices=["bypass", "age"], required=True)
parser.add_argument("--elaboration", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
repo = Path(__file__).resolve().parents[2]
origin = args.elaboration.resolve()
run = args.output.resolve()
if run.exists() or any(c in str(run) for c in "{}\n"):
    raise SystemExit("Output exists or path is unsupported.")

def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def git(*options):
    return subprocess.check_output(["git", "-C", str(repo), *options]).decode().strip()

rtl = origin / "rtl/STTTaintTable.sv"
parameters = (origin / "rtl/parameters.txt").read_text()
settings = dict(item.split("=", 1) for item in parameters.split())
if settings["profile"] != args.profile or settings["mode"] != args.mode:
    raise SystemExit("Elaboration configuration mismatch.")
flow = (origin / "elaboration.log").read_text()
if "STT_RTL_GENERATION_COMPLETE:" not in flow or not re.search(r"Exit status:\s*0\s*$", flow):
    raise SystemExit("Elaboration did not complete successfully.")
if not re.search(r"\bmodule\s+STTTaintTable\s*\(", rtl.read_text()):
    raise SystemExit("Expected module not found.")
subprocess.run(
    ["sha256sum", "-c", str(origin / "source-checksums.sha256")],
    cwd=repo, check=True,
)

library_record = json.loads(
    (repo / "logs/d6-genus-libcheck-01/library-record.json").read_text()
)
library = Path(library_record["resolved_library"])
if digest(library) != library_record["library_sha256"]:
    raise SystemExit("Library hash mismatch.")

template = repo / "scripts/asic/synth-reference.tcl"
text = template.read_text()
old = "USTT_ASIC_TOP USTT_ASIC_DECODE USTT_ASIC_PHY USTT_ASIC_ROB USTT_ASIC_SRC USTT_SKY130_LIB"
if text.count(old) != 1:
    raise SystemExit("Unexpected environment declaration.")
text = text.replace(old, "USTT_ASIC_TOP USTT_ASIC_SRC USTT_SKY130_LIB", 1)
start = text.index("    set sources {}\n")
end_marker = "    elaborate -parameters $parameters $top\n"
end = text.index(end_marker, start) + len(end_marker)
text = text[:start] + (
    "    read_hdl -language sv [file join $src synthesis.v] "
    "[file join $src STTTaintTable.sv]\n"
    "    elaborate $top\n"
) + text[end:]
if text.count("[get_ports clk]") != 2:
    raise SystemExit("Unexpected clock-port references.")
text = text.replace("[get_ports clk]", "[get_ports clock]")

run.mkdir(parents=True)
(run / "sources").mkdir()
(run / "tmp").mkdir()
shutil.copy2(rtl, run / "sources/STTTaintTable.sv")
(run / "sources/synthesis.v").write_text("`define SYNTHESIS\n")
script = run / "synth-taint.tcl"
script.write_text(text)
for name in (
    "source-commit.txt", "source-status.txt",
    "source-checksums.sha256", "elaboration.log",
):
    shutil.copy2(origin / name, run / name)
shutil.copy2(origin / "rtl/parameters.txt", run / "parameters.txt")

inputs = [
    run / "sources/STTTaintTable.sv",
    run / "sources/synthesis.v", script, library,
]
hashes = {str(p): digest(p) for p in inputs}
record = {
    "prepared_at": datetime.now(timezone.utc).isoformat(),
    "top": "STTTaintTable",
    "profile": args.profile, "mode": args.mode,
    "parameters": settings,
    "elaboration_directory": str(origin),
    "elaboration_commit": (origin / "source-commit.txt").read_text().strip(),
    "elaboration_source_checksums": (origin / "source-checksums.sha256").read_text(),
    "repository_commit": git("rev-parse", "HEAD"),
    "working_tree_status": git("status", "--short"),
    "library_record": library_record,
    "reference_tcl_sha256": digest(template),
    "preparer_sha256": digest(Path(__file__).resolve()),
    "files_sha256": hashes,
}
(run / "run-metadata.json").write_text(json.dumps(record, indent=2) + "\n")
(run / "input-checksums.sha256").write_text(
    "".join(value + "  " + name + "\n" for name, value in hashes.items())
)
environment = {
    "CDS_LIC_FILE": "/usr/local/packages/cadence_2022/license.dat",
    "TMPDIR": str(run / "tmp"),
    "USTT_ASIC_TOP": "STTTaintTable",
    "USTT_ASIC_SRC": str(run / "sources"),
    "USTT_SKY130_LIB": str(library),
}
launch = [
    "#!/usr/bin/env bash", "set -euo pipefail",
    "cd " + shlex.quote(str(run)),
    "(set -o noclobber; date -u > started.txt)",
    "sha256sum -c input-checksums.sha256",
]
launch += ["export " + k + "=" + shlex.quote(v) for k, v in environment.items()]
launch.append("exec " + shlex.join([
    "/usr/bin/time", "-v",
    "/usr/local/packages/cadence_2022/GENUS211/bin/genus",
    "-no_gui", "-batch", "-execute", "source {" + str(script) + "}",
]))
(run / "launch.sh").write_text("\n".join(launch) + "\n")
print("Prepared:", run)
