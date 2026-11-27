#!/usr/bin/env python3
"""Snapshot reference inputs and prepare an isolated Genus run."""
import argparse
import hashlib
import json
import shlex
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

profiles = {
    "small": (1, 52, 32),
    "medium": (2, 80, 64),
    "large": (3, 100, 96),
    "mega": (4, 128, 128),
    "giga": (5, 128, 130),
    "reference-8wide": (8, 380, 512),
}
parser = argparse.ArgumentParser()
parser.add_argument("--top", choices=["rename", "stt_og", "stt_age"], required=True)
parser.add_argument("--profile", choices=list(profiles), required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
repo = Path(__file__).resolve().parents[2]
run = args.output.resolve()
if run.exists():
    raise SystemExit("Output already exists: " + str(run))
if any(c in str(run) for c in "{}\n"):
    raise SystemExit("Unsupported output path.")

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def git(*options):
    return subprocess.check_output(["git", "-C", str(repo), *options])

decode, phy, rob = profiles[args.profile]
ref = repo / "reference/uSTT"
if subprocess.check_output(["git", "-C", str(ref), "status", "--porcelain"]).strip():
    raise SystemExit("Reference submodule has changes.")

source = ref / "rtl/src"
if args.top != "rename" or args.profile == "small":
    copies = "d3-reference-init-copies-01" if args.profile == "small" else "d3-reference-copies-01"
    variant = "age-width" if args.top == "stt_age" else "og-bounded"
    source = repo / "logs" / copies / variant
    source_record = json.loads((source / "source-metadata.json").read_text())
else:
    source_record = {"variant": "original-rename"}

names = ("reg", "pe", "eq_comp", "rename", "younger", "stt_control", "stt_og", "stt_age")
for name in names:
    p = source / (name + ".v")
    if not p.is_file():
        raise SystemExit("Missing source: " + str(p))
    expected = source_record.get("source_sha256", {}).get(p.name)
    if expected is not None and digest(p) != expected:
        raise SystemExit("Source hash mismatch: " + str(p))

library_record = json.loads((repo / "logs/d6-genus-libcheck-01/library-record.json").read_text())
library = Path(library_record["resolved_library"])
if digest(library) != library_record["library_sha256"]:
    raise SystemExit("Library hash mismatch.")

run.mkdir(parents=True)
(run / "sources").mkdir()
(run / "tmp").mkdir()
for name in names:
    shutil.copy2(source / (name + ".v"), run / "sources" / (name + ".v"))
script = run / "synth-reference.tcl"
shutil.copy2(repo / "scripts/asic/synth-reference.tcl", script)
inputs = list(sorted((run / "sources").glob("*.v"))) + [script, library]
hashes = {str(p): digest(p) for p in inputs}
record = {
    "prepared_at": datetime.now(timezone.utc).isoformat(),
    "profile": args.profile, "top": args.top,
    "decode": decode, "physical_registers": phy,
    "rob_parameter": rob if args.top != "rename" else None,
    "architectural_registers": 31,
    "repository_commit": git("rev-parse", "HEAD").decode().strip(),
    "working_tree_status": git("status", "--short").decode().strip(),
    "tracked_diff_sha256": hashlib.sha256(git("diff", "HEAD", "--binary")).hexdigest(),
    "reference_commit": subprocess.check_output(
        ["git", "-C", str(ref), "rev-parse", "HEAD"], text=True).strip(),
    "source_directory": str(source),
    "source_copy": source_record,
    "library_record": library_record,
    "files_sha256": hashes,
    "preparer_sha256": digest(Path(__file__).resolve()),
}
(run / "run-metadata.json").write_text(json.dumps(record, indent=2) + "\n")
(run / "input-checksums.sha256").write_text(
    "".join(value + "  " + name + "\n" for name, value in hashes.items())
)

environment = {
    "CDS_LIC_FILE": "/usr/local/packages/cadence_2022/license.dat",
    "TMPDIR": str(run / "tmp"),
    "USTT_ASIC_TOP": args.top,
    "USTT_ASIC_DECODE": str(decode),
    "USTT_ASIC_PHY": str(phy),
    "USTT_ASIC_ROB": str(rob),
    "USTT_ASIC_SRC": str(run / "sources"),
    "USTT_SKY130_LIB": str(library),
}
launch = [
    "#!/usr/bin/env bash", "set -euo pipefail",
    "cd " + shlex.quote(str(run)),
    '(set -o noclobber; date -u > started.txt)',
    "sha256sum -c input-checksums.sha256",
]
launch += ["export " + key + "=" + shlex.quote(value) for key, value in environment.items()]
command = [
    "/usr/bin/time", "-v",
    "/usr/local/packages/cadence_2022/GENUS211/bin/genus",
    "-no_gui", "-batch", "-execute", "source {" + str(script) + "}",
]
launch.append("exec " + shlex.join(command))
(run / "launch.sh").write_text("\n".join(launch) + "\n")
print("Prepared:", run)
print("Inputs and library hashes recorded; launch verifies them again.")
