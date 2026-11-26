#!/usr/bin/env python3
"""Normalize scripts/perf/run.sh results to each config's baseline; write perf.csv and perf.png.

    scripts/perf/report.py [logs/perf/raw.csv] [-o logs/perf]
    scripts/perf/report.py --selftest

Uses each config's latest run (rows sharing a log directory). A config whose latest run has a FAIL row is reported as failed and left out. The baseline of a config is its name with the protected suffix removed, the same rule as classify in scripts/ustt-regress.sh (the selftest checks they agree): MediumBoomV3USTTConfig -> MediumBoomV3Config. cycles_norm is cycles / baseline cycles (above 1 = slower); ipc_norm is ipc / baseline ipc. A geomean row per config covers the benches it shares with its baseline. Rows run with different CoreMark iterations are not normalized against each other. Exits 1 if any config failed or has no baseline.
"""
import argparse
import csv
import math
import os
import re
import sys

FIELDS = ["config", "commit", "baseline", "baseline_commit", "bench",
          "cycles", "instret", "ipc", "cycles_norm", "ipc_norm"]


SUFFIX = "USTT|STTAgeMatrix|STTImpede|STT|Conservative"


def baseline_of(config):
    return re.sub(f"({SUFFIX})Config$", "Config", config)


def latest_runs(rows):
    """config -> rows of its latest run. raw.csv is append-only, so later rows are newer."""
    runs, last = {}, {}
    for r in rows:
        key = (r["commit"], os.path.dirname(r["log"]))
        runs.setdefault((r["config"], key), []).append(r)
        last[r["config"]] = key
    return {c: runs[(c, k)] for c, k in last.items()}


def normalize(rows):
    """Returns (rows for perf.csv, error messages)."""
    errors, last = [], {}
    for config, run in latest_runs(rows).items():
        failed = sorted(r["bench"] for r in run if r["status"] == "FAIL")
        if failed:
            errors.append(f"{config} at {run[0]['commit']} failed {', '.join(failed)} ({os.path.dirname(run[0]['log'])})")
        else:
            last[config] = {r["bench"]: r for r in run if r["status"] == "PASS"}
    out, ratios = [], {}
    for config, benches in last.items():
        base = baseline_of(config)
        if base == config and re.search("STT|USTT|Conservative", config):
            errors.append(f"{config} looks protected but matches no suffix in {SUFFIX}; not normalized")
            base = None
        for bench, r in benches.items():
            b = last.get(base, {}).get(bench) if base else None
            if b and b.get("iterations") != r.get("iterations"):
                print(f"warning: {config} {bench} ran {r.get('iterations')} iterations, {base} ran {b.get('iterations')}; left unnormalized", file=sys.stderr)
                b, base_ok = None, False
            else:
                base_ok = bool(base)
            cyc, ins = int(r["cycles"]), int(r["instret"])
            ipc = ins / cyc
            o = dict(config=config, commit=r["commit"], baseline=base or "",
                     baseline_commit=b["commit"] if b else "", bench=bench,
                     cycles=cyc, instret=ins, ipc=f"{ipc:.4f}", cycles_norm="", ipc_norm="")
            if b:
                cn = cyc / int(b["cycles"])
                ipn = ipc / (int(b["instret"]) / int(b["cycles"]))
                o["cycles_norm"], o["ipc_norm"] = f"{cn:.4f}", f"{ipn:.4f}"
                ratios.setdefault(config, []).append((cn, ipn))
            elif base_ok:
                print(f"warning: no {base} row for {bench}; {config} left unnormalized", file=sys.stderr)
            out.append(o)
    for config, rs in ratios.items():
        g = lambda xs: math.exp(sum(map(math.log, xs)) / len(xs))
        out.append(dict(config=config, commit="", baseline=baseline_of(config), baseline_commit="",
                        bench="geomean", cycles="", instret="", ipc="",
                        cycles_norm=f"{g([c for c, _ in rs]):.4f}", ipc_norm=f"{g([i for _, i in rs]):.4f}"))
    return sorted(out, key=lambda o: (o["config"], o["bench"] == "geomean", o["bench"])), errors


def plot(out, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    benches = sorted({o["bench"] for o in out if o["bench"] != "geomean"}) + ["geomean"]
    configs = sorted({o["config"] for o in out})
    val = {(o["config"], o["bench"]): o for o in out}
    fig, axes = plt.subplots(2, 1, figsize=(max(8, len(benches) * 0.9), 8))
    w = 0.8 / len(configs)
    for k, (ax, key, label) in enumerate(zip(axes, ["ipc", "cycles_norm"], ["IPC", "cycles / baseline"])):
        for j, c in enumerate(configs):
            ys = [float(val[(c, b)][key]) if (c, b) in val and val[(c, b)][key] != "" else 0 for b in benches]
            ax.bar([x + j * w for x in range(len(benches))], ys, w, label=c)
        ax.set_xticks([x + w * (len(configs) - 1) / 2 for x in range(len(benches))])
        ax.set_xticklabels(benches, rotation=45, ha="right")
        ax.set_ylabel(label)
        if key == "cycles_norm":
            ax.axhline(1.0, color="black", linewidth=0.8)
    axes[0].legend(fontsize="small")
    fig.tight_layout()
    fig.savefig(path, dpi=150)


def selftest():
    assert baseline_of("SmallBoomV3Config") == "SmallBoomV3Config"
    assert baseline_of("MediumBoomV3USTTConfig") == "MediumBoomV3Config"
    assert baseline_of("MediumBoomV3ConservativeConfig") == "MediumBoomV3Config"
    assert baseline_of("SmallBoomV3STTAgeMatrixConfig") == "SmallBoomV3Config"
    regress = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ustt-regress.sh")).read()
    m = re.search(r"sed -E 's/\(([^)]*)\)Config\$/Config/'", regress)
    assert m and m.group(1) == SUFFIX, f"classify in ustt-regress.sh uses {m and m.group(1)}, report.py {SUFFIX}"

    def row(c, b, s, cy="", ins="", cm="abc", run=None, it=""):
        return dict(config=c, commit=cm, bench=b, status=s, cycles=cy, instret=ins,
                    log=f"logs/perf/{run or c + '-' + cm}/{b}.log", iterations=it)
    M, S = "MediumBoomV3Config", "MediumBoomV3STTConfig"
    rows = [row(M, "x", "PASS", "999", "1", cm="old"),  # older baseline run, superseded
            row(M, "x", "PASS", "100", "200"),
            row(M, "y", "PASS", "100", "100"),
            row(M, "coremark", "PASS", "100", "100", it="3"),
            row(S, "x", "PASS", "200", "200", cm="def"),
            row(S, "y", "PASS", "800", "100", cm="def"),
            row(S, "pmp", "NO_COUNTERS", cm="def"),
            row(S, "coremark", "PASS", "10", "100", cm="def", it="1")]
    out, errors = normalize(rows)
    out = {(o["config"], o["bench"]): o for o in out}
    assert not errors, errors
    assert out[(M, "x")]["cycles_norm"] == "1.0000" and out[(M, "x")]["cycles"] == 100
    s = out[(S, "x")]
    assert (s["cycles_norm"], s["ipc_norm"], s["baseline_commit"]) == ("2.0000", "0.5000", "abc"), s
    assert out[(S, "geomean")]["cycles_norm"] == "4.0000"  # sqrt(2 * 8); coremark excluded
    assert out[(S, "coremark")]["cycles_norm"] == ""  # 1 vs 3 iterations
    assert (S, "pmp") not in out

    # A newer run with a FAIL hides the older PASS instead of reusing it, and is reported.
    out, errors = normalize(rows + [row(S, "x", "PASS", "300", "300", cm="ghi"), row(S, "y", "FAIL", cm="ghi")])
    assert not any(o["config"] == S for o in out) and len(errors) == 1 and "ghi" in errors[0], errors

    # A protected-looking config with no matching suffix is an error, not 1.0000.
    out, errors = normalize(rows + [row("MediumBoomV3STTFooConfig", "x", "PASS", "300", "200")])
    assert out and len(errors) == 1 and "STTFoo" in errors[0], errors
    assert all(o["cycles_norm"] == "" for o in out if o["config"] == "MediumBoomV3STTFooConfig")
    print("selftest ok")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("raw", nargs="?", default="logs/perf/raw.csv")
    ap.add_argument("-o", "--outdir", default="logs/perf")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    with open(a.raw) as f:
        out, errors = normalize(list(csv.DictReader(f)))
    for e in errors:
        print(f"error: {e}", file=sys.stderr)
    if not out:
        sys.exit(f"no PASS rows in {a.raw}")
    os.makedirs(a.outdir, exist_ok=True)
    csv_path = os.path.join(a.outdir, "perf.csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        w.writerows(out)
    plot(out, os.path.join(a.outdir, "perf.png"))
    print(f"wrote {csv_path} and perf.png")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
