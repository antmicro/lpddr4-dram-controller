proc print_banner {} {
  puts "-----------------------------"
  puts "DRAM Controller"
  puts "Power analysis OpenSTA Script"
  puts "-----------------------------"
}

proc load_libs {lib_dir} {

    # Load PDK cell libraries
    set libs [glob -directory $lib_dir *.lib]
    foreach lib $libs {
        read_liberty $lib
    }
}

proc load_design {netlist top {sdc ""} {spef ""}} {

    # Load and link netlist
    read_verilog $netlist
    link_design $top

    # Load constraints
    if { $sdc ne "" } {
        read_sdc $sdc
    }

    # Load SPEF
    if { $spef ne "" } {
        read_spef $spef
    }
}

proc report_power_sweep { {frequency_list {100.0}} {activity_list {1.0}} } {

  set clk_name "clk"
  set rst_name "rst"

  set_cmd_units -time ns

  foreach frequency $frequency_list {
    set period [expr 1000.0 / $frequency]

    create_clock -name $clk_name -period $period [get_ports $clk_name]
    set_propagated_clock [get_clocks $clk_name]

    foreach activity $activity_list {
        puts "clk_frequency  = $frequency"
        puts "activity_level = $activity"
        set_power_activity -input -activity $activity
        set_power_activity -input_port $rst_name -activity 0
        report_power
    }
  }
}

proc report_power_vcd { vcd scope {frequency_list {100.0}} } {

  set clk_name "clk"
  set rst_name "rst"

  set_cmd_units -time ns

  foreach frequency $frequency_list {
    set period [expr 1000.0 / $frequency]

    create_clock -name $clk_name -period $period [get_ports $clk_name]
    set_propagated_clock [get_clocks $clk_name]

    puts "clk_frequency  = $frequency"
    puts "VCD file       = $vcd"

    read_power_activities -scope $scope -vcd $vcd
    report_power
  }
}
