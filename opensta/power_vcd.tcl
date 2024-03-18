source $::env(ROOT_DIR)/opensta/utils.tcl

print_banner

set lib_dir $::env(OBJECTS_DIR)/lib/
set design  $::env(PROJ)
set netlist $::env(RESULTS_DIR)/6_final.v
set sdc     $::env(RESULTS_DIR)/6_final.sdc
set spef    $::env(RESULTS_DIR)/6_final.spef
set vcd     $::env(ROOT_DIR)/tests/$::env(PDK)_power_analysis.vcd

set frequency_list [split $::env(FREQUENCY_LIST)]

load_libs   $lib_dir
load_design $netlist $design $sdc $spef

report_power_vcd $vcd root/$design $frequency_list

exit
