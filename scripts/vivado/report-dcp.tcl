# Collect supplementary reports from an implemented design.
if {$argc != 1} {
    puts stderr "Usage: report-dcp.tcl <checkpoint.dcp>"
    exit 1
}

if {[catch {
    set checkpoint [file normalize [lindex $argv 0]]
    set report_dir [file join [file dirname $checkpoint] report]
    file mkdir $report_dir
    set_param general.maxThreads 8
    open_checkpoint $checkpoint
    report_power -file [file join $report_dir power.txt]
    check_timing -verbose -file [file join $report_dir timing_checks.txt]
    report_route_status -file [file join $report_dir route_status.txt]
    close_design
} message]} {
    puts stderr "Report generation failed: $message"
    exit 1
}
exit 0
