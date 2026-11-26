# Performance harness (#11)

Cycles and IPC in Verilator for the riscv-tests benchmarks (Dhrystone included) and CoreMark, normalized to the baseline.

```bash
scripts/perf/run.sh MediumBoomV3Config        # appends rows to logs/perf/raw.csv
scripts/perf/run.sh MediumBoomV3STTConfig
scripts/perf/report.py                        # logs/perf/perf.csv and perf.png
scripts/perf/report.py --selftest
```

- `run.sh` re-runs itself through `./ustt`, builds the simulator, runs `run-bmark-tests-fast`, then builds and runs CoreMark (`software/coremark`, `git submodule update --init --recursive software/coremark` once). Run one config at a time.
- Counters are `mcycle`/`minstret` over each benchmark's timed region. CoreMark's bare-metal port only reads `cycle`; `hooks/valgrind/callgrind.h` turns its `CALLGRIND_RUN` hooks into the same `setStats` calls riscv-tests use, without patching the submodule.
- CoreMark runs `CM_ITER` iterations (default 3, the same for every config), not CoreMark's 10-second rule, so it prints `ERROR! Must execute for at least 10 secs`; that line is expected. The run is checked against CoreMark's known list, matrix and state CRCs instead.
- `report.py` takes each config's latest run as a whole, so one config's numbers and geomean come from one build. If that run has a FAIL row the config is reported as failed and left out, rather than falling back to an older PASS. A config's baseline is its name without the `STT`, `STTAgeMatrix`, `STTImpede`, `USTT` or `Conservative` suffix, the same rule as `classify` in `scripts/ustt-regress.sh` (`--selftest` checks they agree). A config whose name contains `STT`, `USTT` or `Conservative` but matches no suffix is an error, not a 1.0000. `baseline_commit` says which run it was normalized against. `report.py` exits 1 on any such error.
- `mm`, `mt-*` and `pmp` print no counters (`mt-*` need several cores, `pmp` is a test) and are recorded as `NO_COUNTERS`. CoreMark without counters is a FAIL: its counter hook stopped working.
- A non-zero exit from `run-bmark-tests-fast`, a timeout included, adds a `riscv-tests` FAIL row, since benchmarks that were killed or never started leave no status file.
- `raw.csv` records CoreMark's iteration count in `iterations`; `report.py` does not normalize across different counts. A `raw.csv` from before that column must be moved aside.
- Memory is DRAMSim2 for every config: every make-driven run gets `+dramsim` from `SIM_FLAGS` in `variables.mk`, and `AbstractConfig` uses `WithBlackBoxSimMem`. `tests/spectre/run.sh` calls the simulator directly and adds `+dramsim` only with `DRAMSIM=1`, so by default the attack runs (#9) use a different memory model from these numbers. Each number comes from one run: Verilator is deterministic.
- A protected config may be normalized against a baseline run at another commit. That holds while the switches-off diff (`scripts/ustt-regress.sh`) passes; rerun the baseline when it does not.
