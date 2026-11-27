#!/usr/bin/env python3
"""Collect implemented-system metrics and hierarchical resource counts."""
import argparse
import csv
import hashlib
import json
import re
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--reports", type=Path, required=True)
parser.add_argument("--flow-log", type=Path, required=True)
parser.add_argument("--config", required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--build-metadata", type=Path)
args = parser.parse_args()

repo = Path(__file__).resolve().parents[2]

def git(*options):
    return subprocess.check_output(["git", "-C", str(repo), *options])

def read(name):
    return (args.reports / name).read_text()

def required(pattern, text):
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        raise ValueError("Required report field missing: " + pattern)
    return match.group(1).strip()

util = read("utilization.txt")
timing = read("timing.txt")
power = read("power.txt")
checks = read("timing_checks.txt")
route = read("route_status.txt")
flow_log = args.flow_log.read_text()

summary = timing.split("Design Timing Summary", 1)[1]
values = None
for line in summary.splitlines():
    fields = line.split()
    if len(fields) == 12:
        try:
            values = [float(value) for value in fields]
        except ValueError:
            continue
        break
if values is None:
    raise ValueError("Timing summary not found")

stamp_path = args.build_metadata or args.reports / "build-metadata.json"
build = {}
if stamp_path.exists():
    build = json.loads(stamp_path.read_text())
    if build["config"] != args.config:
        raise ValueError("Build metadata configuration mismatch")

metadata = {
    "config": args.config,
    "commit": build.get("commit", "unknown"),
    "tracked_diff_sha256": build.get("tracked_diff_sha256", "unknown"),
    "working_tree_status": build.get("working_tree_status", "unknown"),
    "build_recorded_at": build.get("recorded_at", "unknown"),
    "collection_commit": git("rev-parse", "HEAD").decode().strip(),
    "collection_working_tree_status": git("status", "--short").decode().strip(),
    "report_directory": str(args.reports.resolve()),
    "part": required(r"^\|\s*Device\s*:\s*(.*?)\s*\|", util),
    "tool": required(r"^\|\s*Tool Version\s*:\s*(.*?)\s*\|", util),
    "system_wns_ns": values[0],
    "system_tns_ns": values[1],
    "system_whs_ns": values[4],
    "system_ths_ns": values[5],
    "estimated_total_power_w": required(r"\|\s*Total On-Chip Power \(W\)\s*\|\s*([^|]+)", power),
    "power_confidence": required(r"\|\s*Confidence Level\s*\|\s*([^|]+)", power),
    "power_activity_file": required(r"\|\s*Simulation Activity File\s*\|\s*([^|]+)", power),
    "missing_input_delays": required(r"checking no_input_delay \((\d+)\)", checks),
    "missing_output_delays": required(r"checking no_output_delay \((\d+)\)", checks),
    "routing_error_nets": required(r"# of nets with routing errors\.*\s*:\s*(\d+)", route),
    "flow_elapsed": required(r"Elapsed \(wall clock\) time .*?\):\s*(\S+)", flow_log),
    "flow_peak_rss_kib": required(r"Maximum resident set size \(kbytes\):\s*(\d+)", flow_log),
    "flow_exit_status": required(r"Exit status:\s*(\d+)", flow_log),
}

scopes = {
    "VCU118FPGATestHarness", "element_reset_domain_boom_tile",
    "core", "rename_stage", "fp_rename_stage", "rob", "lsu",
    "int_issue_unit", "mem_issue_unit", "fp_issue_unit",
}
optional = {"stt_taint"}
resources = [
    "luts", "logic_luts", "lutram_luts", "srl_luts", "ffs",
    "ramb36", "ramb18", "uram", "dsps",
]
rows = []
seen = set()
for line in util.splitlines():
    if not line.startswith("|"):
        continue
    cells = [cell.strip() for cell in line.split("|")[1:-1]]
    if len(cells) != 11 or cells[0] not in (scopes | optional):
        continue
    scope = cells[0]
    if scope in seen:
        raise ValueError("Ambiguous hierarchy name: " + scope)
    counts = [int(value.replace(",", "")) for value in cells[2:]]
    rows.append(dict(metadata, scope=scope, module=cells[1],
                     **dict(zip(resources, counts))))
    seen.add(scope)

if not scopes <= seen:
    raise ValueError("Missing hierarchy rows: " + ", ".join(sorted(scopes - seen)))

args.output.parent.mkdir(parents=True, exist_ok=True)
with args.output.open("w", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
print("Wrote", len(rows), "resource rows to", args.output)
print("System WNS:", values[0], "ns; WHS:", values[4], "ns")
print("Estimated total power:", metadata["estimated_total_power_w"], "W")
print("Missing I/O delays:", metadata["missing_input_delays"],
      "inputs,", metadata["missing_output_delays"], "outputs")
