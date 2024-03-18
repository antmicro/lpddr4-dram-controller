source $::env(ROOT_DIR)/opensta/power.tcl

set top  "dram_ctrl"
set libs [get_pdk_libs $::env(PDK)]

set netlist $::env(RESULTS_DIR)/6_final.v
set sdc     $::env(RESULTS_DIR)/6_1_fill.sdc
set spef    $::env(RESULTS_DIR)/6_final.spef

load_design $netlist $top $sdc $libs $spef

report_power_sweep "clk" "rst" {100.0 200.0} {0.0 1.0 2.0}

exit
