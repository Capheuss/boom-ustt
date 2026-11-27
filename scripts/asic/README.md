# Standalone Sky130 synthesis

Related issue: #59. Run commands from the repository root.
This evaluates standalone reference circuits and STTTaintTable, not a BOOM core.
The reference/uSTT submodule remains unchanged. Generated artifacts belong in logs/.

## Recorded environment

- Cadence Genus 21.18-s082_1 on mario.ece.utexas.edu.
- Executable: /usr/local/packages/cadence_2022/GENUS211/bin/genus
- Child-process CDS_LIC_FILE: /usr/local/packages/cadence_2022/license.dat
- Volare 0.20.6, isolated in /misc/scratch/kk42389/ustt-asic-tools.
- PDK root: /misc/scratch/kk42389/pdks.
- open_pdks version: c6d73a35f524070e85faff4a6a9eef49553ebc2b.
- Library: sky130_fd_sc_hd__tt_025C_1v80.lib, TT / 25 C / 1.80 V.
- Library SHA256: 8e78e14442062dba34d414fca6490b2f6b96038d4510d1438ca44fee31487135.
- No LEF is loaded into synthesis; the flow uses the library wireload model.
- max_cpus_per_server is 2. Genus can launch additional super-thread server processes.

Install tools and the PDK under your own scratch directory, outside the repository
and home quota. The preparation scripts currently use the recorded server paths.
For another account, update those paths before preparing runs.

## Common synthesis settings

All runs use a 20 ns clock, zero input/output delays, 0.1 ns data-input
transition, 0.01 pF output load and zero clock uncertainty. The clock is ideal.
Generic, mapping and incremental optimization efforts are medium.
Reset and other control inputs retain timing constraints.

synth-reference.tcl is the template used by both preparers. prepare-taint.py
changes only the required environment variables, HDL read/elaboration block
and clock port from clk to clock. It defines SYNTHESIS before reading Chisel RTL.
Each run snapshots its effective Tcl, sources and library hash before launch.

The script reads time and capacitance units from report_units rather than
assuming that Genus attributes or report numbers use particular units.
Timing tables in the recorded runs are in ps.

## Reference inputs

Use scripts/ustt-rtl/prepare-sources.py from PR #58 to create:
- logs/d3-reference-copies-01 with og-bounded and age-width.
- logs/d3-reference-init-copies-01 with --write-enable-init for Small.

Commands:
./ustt python3 scripts/ustt-rtl/prepare-sources.py --output logs/d3-reference-copies-01
./ustt python3 scripts/ustt-rtl/prepare-sources.py --write-enable-init --output logs/d3-reference-init-copies-01

These directories must be unused when generating them. Preserve existing evidence.
The reference submodule must be clean. Copied-source hashes are checked.
Rename uses the original source except Small, which uses the initialization copy.

| Profile | Decode | Integer physical registers | ROB parameter |
| --- | ---: | ---: | ---: |
| small | 1 | 52 | 32 |
| medium | 2 | 80 | 64 |
| large | 3 | 100 | 96 |
| mega | 4 | 128 | 128 |
| giga | 5 | 128 | 130 |
| reference-8wide | 8 | 380 | 512 |

NUM_ARCH remains 31. Rename has no ROB generic. These parameter profiles do not
establish full equivalence to BOOM architectural-register or ROB-wrap semantics.

## Library records

Both preparers read logs/d6-genus-libcheck-01/library-record.json.
For a fresh installation, create a record before synthesis containing at least:
- resolved_library: absolute, version-specific Liberty path.
- library_sha256: SHA256 of that file.
Also record the open_pdks version, Volare version, source URL and corner.
Do not attach a newly created record to a historical run.

The collector also requires logs/d6-area-unit-check-01.json with liberty_sha256.
The recorded check compares sky130_fd_sc_hd__inv_1 Liberty area 3.7536 with its
LEF dimensions 1.38 by 2.72 micrometers. Save the LEF path/hash and dimensions.
This confirms library cell area units; it does not measure placed core area.

## Prepare and launch reference synthesis

Example:
./ustt python3 scripts/asic/prepare-reference.py --top stt_age --profile medium --output logs/NEW-reference

Then launch with a persistent log:
nohup bash logs/NEW-reference/launch.sh > logs/NEW-reference/launch.log 2>&1 < /dev/null &

Use rename or stt_og for the other tops. Use a new directory for every attempt.
launch.sh verifies input hashes and refuses a second start in the same directory.
Inspect ASIC_SYNTHESIS_COMPLETE, process exit status and the actual reports.

## Generate and synthesize our taint table

EmitSTTTaintTable is a test-only main in the boom project.
Invoke through ./ustt and the repository's sbt launcher:
boom / Test / runMain boom.v3.exu.EmitSTTTaintTable medium bypass logs/NEW-elaboration/rtl

Supported profiles: medium and mega. Modes: bypass and age.
Medium uses width 2, 80 integer and 64 FP registers, pregSz 7, robAddrSz 6.
Mega uses width 4, 128 integer and 128 FP registers, pregSz 7, robAddrSz 7.
Both use lregSz 5, include FP state and disable debug-table output ports.
The emitted module has clock/reset ports and unregistered external lane inputs.

Before elaboration, record source-commit.txt, source-status.txt and
source-checksums.sha256 in its parent directory. Record the timed sbt output in
elaboration.log. The checksum manifest uses repository-relative source paths.
The preparer validates that manifest against the current checkout.

Example synthesis preparation:
./ustt python3 scripts/asic/prepare-taint.py --profile medium --mode bypass --elaboration logs/NEW-elaboration --output logs/NEW-taint-synthesis

Launch its launch.sh as above. Do not change sources during elaboration.
The elaboration and synthesis commits are recorded separately.

## Collection and historical evidence

./ustt python3 scripts/asic/collect-results.py --output logs/NEW-summary.csv

The collector has an explicit historical mapping of 18 reference runs and
four Chisel taint runs. Change that mapping for a new run layout.
Output must not already exist. It validates completion, exit status, input
hashes, selected design checks and that all listed undriven hierarchical pins
have fanout zero. Nonzero checks stop collection.

Reports include area, timing, logic levels, detailed design checks, mapped HDL
and applied SDC. Run metadata records effective inputs and provenance.
The original failed unit-query/report-capture attempts remain separate.
Do not commit generated RTL, library files, checkpoints, CSVs or logs.

## Interpretation

Cell area is the sum of mapped library cell areas in square micrometers.
It excludes placement whitespace and is not die area.

The reported first path is the worst setup-slack path selected by Genus.
Its combinational logic delay sums printed cell arcs, excluding clock-to-Q
and net delays. Printed arcs are rounded, so this sum is approximate.
It is not an independent search for the maximum cell-only delay path.

Keep the combinational-cell count on that path separate from Genus's
maximum reported logic-level count. They can describe different paths and
use different counting conventions.

Reference circuits contain interface registers. STTTaintTable has a different
interface and includes integer and FP tag state, clearing and update logic.
Use paired comparisons within each circuit family; their absolute areas and
delays are not interchangeable measures of an integrated BOOM core.

For delay D, total reduction is (D_OG-D_Age)/D_OG.
Extra-delay removal is (D_OG-D_Age)/(D_OG-D_Rename).
Area increase is (A_Age-A_OG)/A_OG. A zero denominator is undefined.

The paper reports 85% logic-delay overhead removal and 36% area increase.
The recorded 8-wide selected-path cell sums give 61.88% and area gives 25.91%.
These measurements do not exactly reproduce those percentages.
Tool version, library version, constraints, path selection and source corrections
must accompany the comparison. No post-route, equivalence or security validation
is claimed by synthesis.

Retain library warnings, including non-monotonic wireload-model adjustments
and unusable physical-only cells, in the evidence and limitations.
