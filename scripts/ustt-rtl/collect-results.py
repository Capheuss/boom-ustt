#!/usr/bin/env python3
"""Collect the recorded D3 synthesis runs without rerunning Vivado."""
import argparse
import csv
import hashlib
import re
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
repo = Path(__file__).resolve().parents[2]

runs = [
    ("reference-8wide", "og-bounded", "logs/d3-synth-og8-bounded-01"),
    ("reference-8wide", "age-width", "logs/d3-synth-age8-fixed-01"),
    ("small", "og-bounded-write-enable-always-comb", "logs/d3-synth-small-og-init-01"),
    ("small", "age-width-write-enable-always-comb", "logs/d3-synth-small-age-init-01"),
    ("medium", "og-bounded", "logs/d3-synth-medium-og-01"),
    ("medium", "age-width", "logs/d3-synth-medium-age-01"),
]
for config in ("large", "mega", "giga"):
    for short, variant in (("og", "og-bounded"), ("age", "age-width")):
        runs.append((config, variant, f"logs/d3-boom-sweep-01/{config}-{short}-synth"))

for config in ("small", "medium", "large", "mega", "giga", "reference-8wide"):
    variant = "rename-write-enable-always-comb" if config == "small" else "rename-original"
    runs.append((config, variant, f"logs/d3-rename-sweep-01/{config}-synth"))

def required(pattern, text):
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        raise ValueError("Required field missing: " + pattern)
    return match.group(1).strip()

rows = []
resources = ("luts", "logic_luts", "lutram_luts", "srl_luts",
             "ffs", "ramb36", "ramb18", "uram", "dsps")

for config, variant, relative in runs:
    directory = repo / relative
    util = (directory / "utilization.txt").read_text()
    timing = (directory / "timing_paths.txt").read_text()
    checks = (directory / "timing_checks.txt").read_text()
    source_record = (directory / "source-record.txt").read_text()
    flow = directory.with_suffix(".log").read_text()

    candidates = []
    for line in util.splitlines():
        if line.startswith("|"):
            cells = [cell.strip() for cell in line.split("|")[1:-1]]
            if len(cells) == 11 and cells[1] == "(top)" and cells[0] in ("rename", "stt_og", "stt_age"):
                candidates.append(cells)
    if len(candidates) != 1:
        raise ValueError("Expected exactly one top resource row: " + relative)
    cells = candidates[0]

    row = {
        "config": config,
        "variant": variant,
        "top": cells[0],
        "decode": required(r"\bdecode=(\d+)", source_record),
        "physical_registers": required(r"\bphy=(\d+)", source_record),
        "rob_parameter": "not_applicable" if cells[0] == "rename" else required(r"\brob=(\d+)", source_record),
        "architectural_registers_parameter": 31,
        "stage": "post_synthesis_estimate",
        "part": required(r"\bpart=(\S+)", source_record),
        "clock_period_ns": required(r"\bclock_period_ns=([\d.]+)", source_record),
        "repository_commit": required(r"^repository_commit=(.+)$", source_record),
        "reference_commit": required(r"^reference_commit=(.+)$", source_record),
        "source_record_sha256": hashlib.sha256(source_record.encode()).hexdigest(),
        "data_path_delay_ns": required(r"Data Path Delay:\s*([\d.]+)ns", timing),
        "logic_levels": required(r"Logic Levels:\s*(\d+)", timing),
        "logic_delay_ns": required(r"Data Path Delay:.*?\(logic\s+([\d.]+)ns", timing),
        "estimated_route_delay_ns": required(r"Data Path Delay:.*?route\s+([\d.]+)ns", timing),
        "loops": required(r"checking loops \((\d+)\)", checks),
        "latch_loops": required(r"checking latch_loops \((\d+)\)", checks),
        "missing_input_delays": required(r"checking no_input_delay \((\d+)\)", checks),
        "missing_output_delays": required(r"checking no_output_delay \((\d+)\)", checks),
        "elapsed": required(r"Elapsed \(wall clock\) time .*?\):\s*(\S+)", flow),
        "peak_rss_kib": required(r"Maximum resident set size \(kbytes\):\s*(\d+)", flow),
        "exit_status": required(r"Exit status:\s*(\d+)", flow),
        "report_directory": str(directory),
    }
    row.update(zip(resources, (int(value.replace(",", "")) for value in cells[2:])))
    rows.append(row)

args.output.parent.mkdir(parents=True, exist_ok=True)
with args.output.open("w", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)

print("Wrote", len(rows), "rows to", args.output)
for row in rows:
    print(row["config"], row["variant"],
          "LUT=" + str(row["luts"]),
          "delay_ns=" + row["data_path_delay_ns"],
          "loops=" + row["loops"],
          "exit=" + row["exit_status"])
