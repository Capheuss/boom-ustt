# Vivado report collection

Run from the repository root using ./ustt.

1. Before a fresh build, record its source version:
   ./ustt python3 scripts/vivado/stamp-build.py --config CONFIG --output logs/RUN-build.json
2. Run the full flow under /usr/bin/time -v:
   nohup /usr/bin/time -v ./ustt --vivado make -C fpga SUB_PROJECT=vcu118 CONFIG=CONFIG bitstream > logs/RUN-flow.log 2>&1 < /dev/null &
3. Wait for completion and inspect the exit status. On the checkpoint from that run, execute:
   ./ustt --vivado vivado -mode batch -nojournal -source scripts/vivado/report-dcp.tcl -tclargs BUILD/obj/post_route.dcp
4. Collect the reports:
   ./ustt python3 scripts/vivado/collect-reports.py --reports BUILD/obj/report --flow-log logs/RUN-flow.log --config CONFIG --build-metadata logs/RUN-build.json --output logs/RUN-summary.csv

Replace CONFIG, RUN and BUILD with the configuration, unique run name and
generated-source directory. BUILD normally means:
fpga/generated-src/chipyard.fpga.vcu118.VCU118FPGATestHarness.CONFIG

Check machine load before starting. Run long commands in the background with logs.
Do not change sources or branches during a build. Commit relevant sources first.
Archive existing configuration outputs before a fresh measurement: make may
otherwise reuse cached outputs. Never associate a new stamp with old results.
The stamp records tracked changes and working-tree status, but not untracked
file contents. It refuses to overwrite an existing provenance file.

The CSV includes core and an optional stt_taint row. Duplicate selected instance
names are rejected. Parent resource totals already include their descendants.
System timing columns apply to the whole design, not individual resource rows.
A timing failure can still produce a CSV: inspect flow_exit_status and slack.
Earlier failures may prevent collection if required reports are missing.
Power is vectorless and estimated; retain confidence and missing I/O delays.

Without a build stamp, build provenance is unknown. Collection-time metadata
is separate. Git queries use the script's repository, regardless of the current
directory. The original Medium result came from b1904732 plus the uncommitted
FPGA config later included in b6de1dc8; no build-time stamp was captured.

Keep generated reports, logs and CSV files out of commits.
