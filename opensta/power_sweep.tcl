source $::env(ROOT_DIR)/opensta/utils.tcl

print_banner

set lib_dir $::env(OBJECTS_DIR)/lib/
set design  $::env(PROJ)
set netlist $::env(RESULTS_DIR)/6_final.v
set spef    $::env(RESULTS_DIR)/6_final.spef

set frequency_list [split $::env(FREQUENCY_LIST)]
set activity_list  [split $::env(ACTIVITY_LIST)]

load_libs   $lib_dir
load_design $netlist $design "" $spef

report_power_sweep $frequency_list $activity_list

exit
