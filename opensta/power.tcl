# report_power gcd

proc print_banner {} {
  puts "-----------------------------"
  puts "DRAM Controller"
  puts "Power analysis OpenSTA Script"
  puts "-----------------------------"
}

proc setup { design lib_dir ver_file sdc_file spf_file } {
  set lib_list [glob -directory $lib_dir *.lib]
  foreach lib_file $lib_list {
    read_liberty $lib_file
  }
  read_verilog $ver_file
  link_design $design
  read_sdc $sdc_file
  read_spef $spf_file
}

proc analysis { activity_list } {
  set_power_activity -input_port rst -activity 0
  foreach activity_level $activity_list {
      puts "activity_level = $activity_level"
      set_power_activity -input -activity $activity_level
      report_power
  }
}

proc report_activities { design lib_dir ver_file sdc_file spf_file activity_list } {
  print_banner
  setup $design $lib_dir $ver_file $sdc_file $spf_file
  analysis $activity_list
}


# set FLOW_DIR third_party/OpenROAD-flow-scripts/flow/
# set PDK asap7
# set DESIGN ander
# set ACTIVITY_LIST {0.0 0.5 1.0}

set FLOW_DIR $::env(FLOW_DIR)
set PDK $::env(PDK)
set DESIGN $::env(DESIGN)
set ACTIVITY_LIST [split $::env(ACTIVITY_LIST)]

set ver_file $FLOW_DIR/results/$PDK/$DESIGN/base/6_final.v
set sdc_file $FLOW_DIR/results/$PDK/$DESIGN/base/6_final.sdc
set spf_file $FLOW_DIR/results/$PDK/$DESIGN/base/6_final.spef
set lib_dir $FLOW_DIR/objects/$PDK/$DESIGN/base/lib/

report_activities $DESIGN $lib_dir $ver_file $sdc_file $spf_file $ACTIVITY_LIST
