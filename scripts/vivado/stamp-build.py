#!/usr/bin/env python3
"""Record source provenance immediately before starting a hardware build."""
import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--config", required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()

repo = Path(__file__).resolve().parents[2]

def git(*options):
    return subprocess.check_output(["git", "-C", str(repo), *options])

diff = git("diff", "HEAD", "--binary")
record = {
    "config": args.config,
    "commit": git("rev-parse", "HEAD").decode().strip(),
    "tracked_diff_sha256": hashlib.sha256(diff).hexdigest(),
    "working_tree_status": git("status", "--short").decode().strip(),
    "recorded_at": datetime.now(timezone.utc).isoformat(),
    "repository": str(repo),
}

args.output.parent.mkdir(parents=True, exist_ok=True)
with args.output.open("x") as stream:
    json.dump(record, stream, indent=2)
    stream.write("\n")
print("Recorded source provenance in", args.output)
