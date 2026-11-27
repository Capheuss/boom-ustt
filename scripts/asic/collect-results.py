#!/usr/bin/env python3
"""Validate and collect the recorded 22 Genus synthesis runs."""
import argparse
import csv
import hashlib
import json
import re
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
repo = Path(__file__).resolve().parents[2]

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def required(pattern, text):
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        raise ValueError("Missing required field: " + pattern)
    return match[1]

runs = [
    repo / "logs/d6-ref8-rename-05",
    repo / "logs/d6-ref8-og-01",
    repo / "logs/d6-ref8-age-01",
]
runs += [
    repo / "logs/d6-boom-reference-sweep-01" / f"{profile}-{top}"
    for profile in ("small", "medium", "large", "mega", "giga")
    for top in ("rename", "stt_og", "stt_age")
]
runs += [
    repo / f"logs/d6-taint-{profile}-{mode}-synth-01"
    for profile in ("medium", "mega")
    for mode in ("bypass", "age")
]

unit_proof = json.loads((repo / "logs/d6-area-unit-check-01.json").read_text())
rows = []
verified = {}
for run in runs:
    metadata_path = run / "run-metadata.json"
    metadata = json.loads(metadata_path.read_text())
    library = metadata["library_record"]
    if library["library_sha256"] != unit_proof["liberty_sha256"]:
        raise ValueError("Area-unit proof uses another library: " + str(run))
    for filename, expected in metadata["files_sha256"].items():
        source = Path(filename)
        actual = verified.get(str(source))
        if actual is None:
            actual = digest(source)
            verified[str(source)] = actual
        if actual != expected:
            raise ValueError("Input hash mismatch: " + filename)

    log = (run / "launch.log").read_text()
    if "ASIC_SYNTHESIS_COMPLETE" not in log.splitlines():
        raise ValueError("Missing completion: " + str(run))
    if not re.search(r"Exit status:\s*0\s*$", log):
        raise ValueError("Failed or incomplete run: " + str(run))

    reports = run / "reports"
    checks = (reports / "design_checks.rpt").read_text()
    for field in (
        "Unresolved References", "Empty Modules",
        "Undriven Port(s)", "Undriven Leaf Pin(s)",
        "Multidriven Port(s)", "Multidriven Leaf Pin(s)",
        "Multidriven hierarchical Pin(s)", "Multidriven unloaded net(s)",
    ):
        count = int(required("^" + re.escape(field) + r"\s+(\d+)\s*$", checks))
        if count:
            raise ValueError(f"{run}: investigate {field}={count}")
    undriven = int(required(r"^Undriven hierarchical pin\(s\)\s+(\d+)", checks))
    details = (reports / "design_checks_detailed.rpt").read_text()
    pins = [line for line in details.splitlines() if line.startswith("hpin:")]
    if len(pins) != undriven:
        raise ValueError("Hierarchical-pin count mismatch: " + str(run))
    if any(not re.search(r"fanout\s*:\s*0\s*\)", line) for line in pins):
        raise ValueError("Undriven pin has a load: " + str(run))

    area_text = (reports / "area_summary.rpt").read_text()
    module = required(r"^\s*Module:\s*(\S+)", area_text)
    area_rows = [
        line.split() for line in area_text.splitlines()
        if line.split() and line.split()[0] == module
    ]
    if len(area_rows) != 1 or not area_rows[0][1].isdigit():
        raise ValueError("Ambiguous area row: " + str(run))
    area = area_rows[0]

    timing = (reports / "timing.rpt").read_text()
    first = timing.split("Path 1:", 1)[1].split("Path 2:", 1)[0]
    if not re.search(r"\(ps\)\s+\(ps\)", first):
        raise ValueError("Unexpected timing units: " + str(run))
    comb, clkq = [], []
    for line in first.splitlines():
        fields = line.split()
        if len(fields) != 5 or not fields[2].startswith("sky130_fd_sc_hd__"):
            continue
        if fields[1] == "CLK->Q":
            clkq.append(float(fields[3]))
        elif "->" in fields[1]:
            comb.append(float(fields[3]))
    if not comb:
        raise ValueError("No combinational arcs: " + str(run))

    levels_text = (reports / "logic_levels.rpt").read_text()
    levels = [int(n) for n in re.findall(r"\}\s+(\d+)\}", levels_text)]
    if not levels:
        raise ValueError("Missing logic-level results: " + str(run))
    units = dict(line.split("=", 1)
                 for line in (reports / "units.txt").read_text().splitlines())
    if (units["clock_period_ns"], units["input_transition_ns"],
            units["output_load_pf"]) != ("20", "0.1", "0.01"):
        raise ValueError("Constraint mismatch: " + str(run))

    row = {
        "profile": metadata["profile"],
        "top": metadata["top"],
        "mode": metadata.get("mode", metadata.get("source_copy", {}).get("variant", "")),
        "cell_count": int(area[1]),
        "cell_area_um2": float(area[2]),
        "first_setup_path_delay_ns": float(required(r"Data Path:-\s*([\d.]+)", first))/1000,
        "first_setup_path_comb_logic_ns_rounded": sum(comb)/1000,
        "first_setup_path_comb_levels": len(comb),
        "first_setup_path_clkq_ns_rounded": sum(clkq)/1000,
        "first_setup_path_slack_ns": float(required(r"Slack:=\s*([-+\d.]+)", first))/1000,
        "max_reported_logic_levels": max(levels),
        "startpoint": required(r"^\s*Startpoint:\s*(.+)", first),
        "endpoint": required(r"^\s*Endpoint:\s*(.+)", first),
        "unloaded_ports": int(required(r"^Unloaded Port\(s\)\s+(\d+)", checks)),
        "undriven_hierarchical_pins_fanout_zero": undriven,
        "clock_period_ns": units["clock_period_ns"],
        "input_transition_ns": units["input_transition_ns"],
        "output_load_pf": units["output_load_pf"],
        "tool": required(r"^\s*Generated by:\s*(.+)", area_text),
        "operating_conditions": required(r"^\s*Operating conditions:\s*(.+)", area_text),
        "wireload_mode": required(r"^\s*Wireload mode:\s*(.+)", area_text),
        "elapsed": required(r"Elapsed \(wall clock\) time .*?\):\s*(\S+)", log),
        "peak_rss_kib": required(r"Maximum resident set size \(kbytes\):\s*(\d+)", log),
        "exit_status": 0,
        "repository_commit": metadata["repository_commit"],
        "elaboration_commit": metadata.get("elaboration_commit", ""),
        "reference_commit": metadata.get("reference_commit", ""),
        "run_metadata_sha256": digest(metadata_path),
        "run_metadata_json": json.dumps(metadata, sort_keys=True),
        "report_directory": str(run),
    }
    rows.append(row)

args.output.parent.mkdir(parents=True, exist_ok=True)
with args.output.open("x", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
print("Validated and wrote", len(rows), "rows to", args.output)
print("profile top mode area_um2 path_ns comb_ns slack_ns")
for row in rows:
    print(row["profile"], row["top"], row["mode"],
          f'{row["cell_area_um2"]:.3f}',
          f'{row["first_setup_path_delay_ns"]:.3f}',
          f'{row["first_setup_path_comb_logic_ns_rounded"]:.3f}',
          f'{row["first_setup_path_slack_ns"]:.3f}')
