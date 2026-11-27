#!/usr/bin/env python3
"""Prepare deterministic reference vectors and portable testbench copies."""
import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--top", choices=["rename", "stt_og", "stt_age"], required=True)
parser.add_argument("--decode", type=int, default=10)
parser.add_argument("--phy", type=int, default=380)
parser.add_argument("--rob", type=int, default=512)
parser.add_argument("--seed", type=int, default=1)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()

if args.decode < 1 or args.phy < 31 + args.decode or args.rob < 2:
    raise SystemExit("Invalid test parameters")
out = args.output.resolve()
out.mkdir(parents=True, exist_ok=False)
repo = Path(__file__).resolve().parents[2]
ref = repo / "reference/uSTT"
rtl = ref / "rtl"
og = args.top == "stt_og"
files = {
    "rename": ("RenameTestGen.py", "rename_testbench.v"),
    "stt_og": ("OGSTTTestGen.py", "stt_og_testbench.v"),
    "stt_age": ("STTTestGen.py", "stt_testbench.v"),
}
generator_name, bench_name = files[args.top]
generator = rtl / "test" / generator_name
bench = rtl / "src" / bench_name
width = lambda value: max(1, math.ceil(math.log2(value)))
settings = {
    "NUM_DECODE": args.decode, "NUM_ARCH": 31,
    "NUM_PHY": args.phy, "NUM_ROB": args.rob,
    "DECODE_WIDTH": width(args.decode), "PHY_WIDTH": width(args.phy),
    "ARCH_WIDTH": 5, "YROT_WIDTH": width(args.rob),
}
if args.top == "rename":
    settings.pop("NUM_ROB")
    settings.pop("YROT_WIDTH")
source = generator.read_text()
for name, value in settings.items():
    source, count = re.subn(r"^" + name + r"\s*=\s*\d+\s*$",
                           name + " = " + str(value), source, flags=re.M)
    if count != 1:
        raise SystemExit("Unexpected generator parameter: " + name)
source = source.replace("random.seed(os.urandom(32))",
                        "random.seed(" + str(args.seed) + ")")
source = re.sub(r"^DEBUG\s*=\s*True", "DEBUG = False", source, flags=re.M)
(out / "generator.py").write_text(source)
with (out / "generator.log").open("w") as log:
    subprocess.run([sys.executable, "generator.py"], cwd=out,
                   stdout=log, stderr=subprocess.STDOUT, check=True)
vectors = list(out.glob("*.input"))
if len(vectors) != 1:
    raise SystemExit("Expected exactly one vector file")
lines = vectors[0].read_text().splitlines()
if len(lines) < 2 or any(not line or set(line) - {"0", "1"} for line in lines):
    raise SystemExit("Invalid or insufficient test vectors")

tb = bench.read_text()
if args.top == "rename":
    if tb.count("module rename_testbench;") != 1:
        raise SystemExit("Unexpected rename testbench module")
    tb = tb.replace("module rename_testbench;", "module stt_testbench;", 1)
for name, value in settings.items():
    tb, count = re.subn(r"(`define\s+" + name + r"\s+)\S+",
                       lambda m: m[1] + str(value), tb)
    if count != 1:
        raise SystemExit("Unexpected testbench parameter: " + name)
tb, count = re.subn(r'\$readmemb\("[^"]+"',
                   '$readmemb("' + vectors[0].name + '"', tb)
if count != 1:
    raise SystemExit("Unexpected vector path")
tb = re.sub(r"localparam testcases\s*=\s*\d+;",
            "localparam testcases = " + str(len(lines)) + ";", tb)
tb = re.sub(r"\$vcdplus(?:on|memon|off)\s*;", "", tb)
if og:
    tb = tb.replace("4*`PHY_WIDTH", "3*`PHY_WIDTH")
# Preserve the reference failure diagnostics.
(out / "testbench.sv").write_text("`timescale 1ns/1ps\n" + tb)
record = dict(vars(args))
record["output"] = str(out)
record["vector_count"] = len(lines)
record["vector_sha256"] = hashlib.sha256(vectors[0].read_bytes()).hexdigest()
record["reference_commit"] = subprocess.check_output(
    ["git", "-C", str(ref), "rev-parse", "HEAD"]).decode().strip()
(out / "test-metadata.json").write_text(json.dumps(record, indent=2) + "\n")
print("Prepared", args.top, "with", len(lines), "vectors in", out)
