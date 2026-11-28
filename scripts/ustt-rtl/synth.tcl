if {[llength $argv] != 6} {
    puts stderr "Usage: TOP DECODE PHY ROB SOURCE_DIR OUTPUT_DIR"
    exit 1
}

if {[catch {
    lassign $argv top decode phy rob src out
    set src [file normalize $src]
    set out [file normalize $out]
    if {[file exists $out]} {
        error "Output directory already exists: $out"
    }
    file mkdir $out

    set repo [file normalize [file join [file dirname [info script]] ../..]]
    set part xcvu9p-flga2104-2L-e
    set_param general.maxThreads 2

    set sources {}
    foreach name {reg pe eq_comp rename younger stt_control stt_og stt_age} {
        lappend sources [file join $src $name.v]
    }

    set stamp [open [file join $out source-record.txt] w]
    puts $stamp "Recorded before synthesis: [clock format [clock seconds] -gmt 1]"
    puts $stamp "top=$top decode=$decode phy=$phy rob=$rob part=$part clock_period_ns=20"
    puts $stamp "repository_commit=[exec git -C $repo rev-parse HEAD]"
    puts $stamp "reference_commit=[exec git -C [file join $repo reference/uSTT] rev-parse HEAD]"
    puts $stamp "Working tree:\n[exec git -C $repo status --short]"
    puts $stamp "Tracked diff:\n[exec git -C $repo diff HEAD --binary]"
    puts $stamp "Source hashes:\n[exec sha256sum {*}$sources]"
    puts $stamp "Script hash:\n[exec sha256sum [info script]]"
    close $stamp

    create_project -in_memory -part $part
    read_verilog -sv $sources

    set xdc [file join $out clock.xdc]
    set stream [open $xdc w]
    puts $stream {create_clock -name clk -period 20.000 [get_ports clk]}
    close $stream
    read_xdc -mode out_of_context $xdc

    set generics [list -generic NUM_DECODE=$decode \
        -generic NUM_PHY=$phy -generic NUM_ARCH=31]
    if {$top ne "rename"} {
        lappend generics -generic NUM_ROB=$rob
    }
    synth_design -top $top -part $part \
        -mode out_of_context -flatten_hierarchy rebuilt {*}$generics

    write_checkpoint -force [file join $out post_synth.dcp]
    report_utilization -hierarchical -file [file join $out utilization.txt]
    report_timing_summary -file [file join $out timing_summary.txt]
    report_timing -delay_type max -max_paths 20 \
        -file [file join $out timing_paths.txt]
    check_timing -verbose -file [file join $out timing_checks.txt]
    puts "SYNTHESIS COMPLETE: $out"
} message]} {
    puts stderr "Synthesis failed: $message"
    exit 1
}
exit 0
