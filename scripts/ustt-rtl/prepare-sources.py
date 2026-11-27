#!/usr/bin/env python3
"""Prepare explicitly patched copies; never modify the reference submodule."""
import argparse
import difflib
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--write-enable-init", action="store_true")
args = parser.parse_args()

repo = Path(__file__).resolve().parents[2]
reference = repo / "reference/uSTT"
source = reference / "rtl/src"
output = args.output.resolve()
if output.exists():
    raise SystemExit("Output already exists: " + str(output))

original_og = (source / "stt_og.v").read_text()
anchor = "            wire [YROT_WIDTH-1:0] yrot1;"
selection = ": output_yrots[raw_pri_out_matrix"
if original_og.count(anchor) != 1 or original_og.count(selection) != 2:
    raise SystemExit("Unexpected stt_og source.")

extra = """
            wire [YROT_WIDTH-1:0] prior_output_yrots [i-1:0];
            for (genvar p = 0; p < i; p = p+1) begin : copy_prior
                assign prior_output_yrots[p] = output_yrots[p];
            end
"""
fixed_og = original_og.replace(anchor, extra + "\n" + anchor, 1)
fixed_og = fixed_og.replace(selection, ": prior_output_yrots[raw_pri_out_matrix")

original_younger = (source / "younger.v").read_text()
old = "wire [$clog2(i+1)+1-1:0] pri_out;"
new = "wire [$clog2(i+2)-1:0] pri_out;"
if original_younger.count(old) != 1:
    raise SystemExit("Unexpected branch epoch source.")
fixed_younger = original_younger.replace(old, new, 1)

init_patch = ""
rename_after = None
if args.write_enable_init:
    rename_before = (source / "rename.v").read_text()
    old_block = "always @(*) begin\n                write_en[i] = 1'b1;"
    new_block = "always_comb begin\n                write_en[i] = 1'b1;"
    if rename_before.count(old_block) != 2:
        raise SystemExit("Unexpected write-enable blocks.")
    rename_after = rename_before.replace(old_block, new_block)
    init_patch = "".join(difflib.unified_diff(
        rename_before.splitlines(keepends=True),
        rename_after.splitlines(keepends=True),
        fromfile="original/rename.v", tofile="write-enable-init/rename.v",
    ))

reference_commit = subprocess.check_output(
    ["git", "-C", str(reference), "rev-parse", "HEAD"], text=True
).strip()

for variant, filename, before, after in [
    ("og-bounded", "stt_og.v", original_og, fixed_og),
    ("age-width", "younger.v", original_younger, fixed_younger),
]:
    dest = output / variant
    shutil.copytree(source, dest)
    (dest / filename).write_text(after)
    if rename_after is not None:
        (dest / "rename.v").write_text(rename_after)
    patch = "".join(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile="original/" + filename, tofile=variant + "/" + filename,
    ))
    (dest / "changes.patch").write_text(patch + init_patch)
    record = {
        "variant": variant + ("-write-enable-always-comb" if args.write_enable_init else ""),
        "reference_commit": reference_commit,
        "source_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(dest.glob("*.v"))
        },
    }
    (dest / "source-metadata.json").write_text(json.dumps(record, indent=2) + "\n")
    print("Prepared:", dest)
