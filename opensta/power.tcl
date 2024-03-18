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

proc get_pdk_libs {pdk} {
    if { $pdk eq "sky130hd" } {
        set libs "$::env(TP_ORFS_DIR)/flow/platforms/sky130hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib"
    
    elseif { $pdk eq "sky130hd" } {
#       set libs {
#           $::env(TP_ORFS_DIR)/
# TODO

    } else {
        error "Standard cell library for PDK '$pdk' not known"
    }

    return $libs
}

proc load_design {netlist top {sdcs {}} {libs {}} {spef ""}} {

    # Load libraries
    foreach lib $libs {
        puts "Loading lib '$lib'"
        read_liberty $lib
    }

    # Load netlist
    puts "Loading netlist '$netlist'"
    read_verilog $netlist

    link_design $top

    # Load constraints
    foreach sdc $sdcs {
        puts "Loading sdc '$sdc'"
        read_sdc $sdc
    }

    # Load SPEF if exists
    if { $spef ne "" } {
        puts "Loading spef '$spef'"
        read_spef $spef
    }
}

proc report_power_sweep { {clk_name "clk"} {rst_name "rst"} {freqs {100.0}} {activities {1.0}} } {

  foreach freq $freqs {

    set period [expr 1e-6 / $freq]

    create_clock -name $clk_name -period $period {clk}
#    set_input_delay -clock clk 0 {d1 d2}

    foreach activity $activities {
        puts "clk_period     = $period"
        puts "activity_level = $activity"
        set_power_activity -input -activity $activity
        set_power_activity -input_port $rst_name -activity 0
        report_power
    }
  }
}

proc report_activities { design lib_dir ver_file sdc_file spf_file activity_list } {
  print_banner
  setup $design $lib_dir $ver_file $sdc_file $spf_file
  analysis $activity_list
}

set FLOW_DIR $::env(FLOW_DIR)
set PDK $::env(PDK)
set DESIGN $::env(DESIGN)
set ACTIVITY_LIST [split $::env(ACTIVITY_LIST)]

set ver_file $FLOW_DIR/results/$PDK/$DESIGN/base/6_final.v
set sdc_file $FLOW_DIR/results/$PDK/$DESIGN/base/6_final.sdc
set spf_file $FLOW_DIR/results/$PDK/$DESIGN/base/6_final.spef
set lib_dir $FLOW_DIR/objects/$PDK/$DESIGN/base/lib/

report_activities $DESIGN $lib_dir $ver_file $sdc_file $spf_file $ACTIVITY_LIST
