# Standalone uSTT RTL evaluation

Related issue: #14. Run from the repository root through ./ustt.
reference/uSTT remains read-only. Generated files belong in logs/.

## Scope and configurations

These are standalone rename circuits, not complete BOOM cores.
All runs use Vivado 2023.2.2, xcvu9p-flga2104-2L-e, out-of-context
synthesis, rebuilt hierarchy, a 20 ns clock and at most two threads.

| Profile | Decode | Int physical registers | ROB parameter |
| --- | ---: | ---: | ---: |
| Small | 1 | 52 | 32 |
| Medium | 2 | 80 | 64 |
| Large | 3 | 100 | 96 |
| Mega | 4 | 128 | 128 |
| Giga | 5 | 128 | 130 |
| Reference | 8 | 380 | 512 |

NUM_ARCH remains 31. FP profiles are not evaluated. Rename-only has no
ROB generic. Non-power-of-two ROB parameters retain the reference index
encoding; this does not establish equivalence to BOOM's ROB behavior.

## Source preparation

prepare-sources.py --output logs/NEW creates two explicit variants:

- og-bounded limits YRoT selection to preceding instructions.
- age-width corrects the branch epoch priority-output wire width.
Add --write-enable-init for Small's write_en always_comb correction.
Each variant includes changes.patch and source-metadata.json.

Original failing runs are preserved. Modified-copy passes do not mean
the unmodified reference passes.

## Functional tests

Example preparation:
./ustt python3 scripts/ustt-rtl/prepare-test.py --top stt_age --decode 2 --phy 80 --rob 64 --seed 1 --output logs/NEW-test

Example execution:
env USTT_RTL_SRC="$PWD/logs/NEW/age-width" ./ustt --vivado bash scripts/ustt-rtl/run-xsim.sh logs/NEW-test

Use rename or stt_og for the other tops. Use a new directory per run.
The copied benches use actual vector counts, portable vector paths and
timescales, remove VCS waveform tasks and normalize the bench module name.
The OG bench's physical-register output width is corrected from four
fields to three. Expected-value generation and failure checks are retained.
TESTSYN checks outputs, not complete internal RAT state.

The runner rejects tool errors, timeouts, FAIL markers, missing completion
and incorrect PASS counts. Each tool stage has a 300-second timeout.
New runs record effective source and test/tooling hashes before compilation.
Historical runs must not be retroactively stamped.
These are RTL tests, not post-synthesis simulation or security validation.

## Synthesis

Example; launch long runs in the background with a log and /usr/bin/time -v:
./ustt --vivado vivado -mode batch -nojournal -source scripts/ustt-rtl/synth.tcl -tclargs stt_age 2 80 64 logs/NEW/age-width logs/NEW-synth

Arguments: TOP DECODE PHY ROB SOURCE_DIR OUTPUT_DIR.
For rename, ROB is only a configuration label. Output must not exist.
source-record.txt captures source/script hashes, Git state, part and clock.
Do not change sources during a run. Inspect exit status, critical warnings,
loop checks and timing paths; successful synthesis alone is insufficient.

## Historical batches and collection

run-boom-sweep.sh records the initial paired sweep; its Small tests fail.
Corrected Small tests and synthesis were run separately.
run-rename-sweep.sh covers six profiles, reuses the Medium rename test,
and uses logs/d3-small-og-init-src-01 for Small. That source is reproducible
with prepare-sources.py --write-enable-init; preserve the expected path.

Batch scripts use fixed paths. Archive outputs before a fresh reproduction.
collect-results.py has an explicit historical run mapping, not automatic
discovery. For another layout, update that mapping. Each flow log must be
named REPORT_DIRECTORY.log.

./ustt python3 scripts/ustt-rtl/collect-results.py --output logs/d3-summary-with-rename.csv

The CSV records 18 synthesis rows, variants, provenance, resources, delay
components, logic levels, loop counts, missing I/O delays, runtime and RSS.
Keep generated RTL, checkpoints, reports, CSVs and logs out of commits.

## Interpretation and paper comparison

Top totals include rename state and input/output registers. Rebuilding may
move logic across module boundaries. These are post-synthesis estimates:
routing is estimated, I/O delays are incomplete, and OOC clock placement
does not establish integrated clock delay/skew.

Paper: https://bluechen8.github.io/files/ustt.pdf , Section VI-A/Figure 7.
It uses Cadence/Skywater 130 nm ASIC synthesis. LUTs are not ASIC area.
The project's standalone ROB 512 differs from the gem5 table's ROB 330.

For a specified delay metric D:

- Total reduction = (D_OG - D_Age) / D_OG.
- Extra-delay removal = (D_OG - D_Age) / (D_OG - D_Rename).

The second ratio is undefined for a zero denominator. Distinguish total
estimated path delay from cell-logic delay. Worst total-delay paths need
not be worst cell-only paths. Do not claim exact ASIC percentage reproduction.
Post evidence and original failures on #14; modified scope requires review.
