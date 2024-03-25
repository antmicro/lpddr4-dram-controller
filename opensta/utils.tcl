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

proc extract_power_report_data { data } {
  set totals        [lrange $data  0  3]
  set sequential    [lrange $data  4  7]
  set combinational [lrange $data  8 11]
  set clock         [lrange $data 12 15]
  set macro         [lrange $data 16 19]
  set pad           [lrange $data 20 end]

  set report ""
  set rows   {"internal" "switching" "leakage" "total"}

  for {set i 0} {$i < 4} {incr i} { 
    set col ""

    dict append col "sequential"    [lindex $sequential    $i]
    dict append col "combinational" [lindex $combinational $i]
    dict append col "clock"         [lindex $clock         $i]
    dict append col "macro"         [lindex $macro         $i]
    dict append col "pad"           [lindex $pad           $i]

    # Compute total
    set total 0.0
    foreach val [dict values $col] {
        set total [expr $total + $val]
    }
    dict append col "total" $total

    dict append report [lindex $rows $i] $col
  }

  return $report
}

proc write_power_report_json { frequency activity report prefix file_name } {
    set fp [open $file_name "w"]
    puts $fp "{"

    # Format "header" data
    puts $fp "  \"frequency\": $frequency,"
    puts $fp "  \"activity\": $activity,"
    puts $fp "  \"results\": {"

    # Format lines
    set lines ""
    foreach row_key [dict keys $report] {
        set row [dict get $report $row_key]
        foreach col_key [dict keys $row] {
            set val [dict get $row $col_key]
            set line "    \"${prefix}__power__${row_key}__${col_key}\": $val"
            lappend lines $line
        }
    }

    # Output lines (except the last one)
    for {set i 0} {$i < [expr [llength $lines] - 1]} {incr i} {
        set line [lindex $lines $i]
        puts $fp "$line,"
    }

    # Output the last line without comma
    set line [lindex $lines $i]
    puts $fp $line

    puts $fp "  }"
    puts $fp "}"
    close $fp
}

proc report_power_sweep { {frequency_list {100.0}} {activity_list {1.0}} } {

  set clk_name "clk"
  set rst_name "rst"

  set_cmd_units -time ns

  global sta_report_default_digits
  set corner [sta::parse_corner "-digits $sta_report_default_digits"]

  foreach frequency $frequency_list {
    set period [expr 1000.0 / $frequency]

    create_clock -name $clk_name -period $period $clk_name
    set_propagated_clock [get_clocks $clk_name]

    foreach activity $activity_list {
        puts "clk_frequency  = $frequency (T=$period)"
        puts "activity_level = $activity"
        set_power_activity -input -activity $activity
        set_power_activity -input_port [get_ports $rst_name] -activity 0.05

        # Report power to the log
        report_power

        # Report power to a JSON file
        set report [sta::design_power $corner]
        set report [extract_power_report_data $report]

        set f_mhz [expr int($frequency)]
        set a_percent [expr int($activity * 100.0)]

        set file_name "$::env(RESULTS_DIR)/power_analysis_sweep_f${f_mhz}_a${a_percent}.json"
        write_power_report_json $frequency $activity $report "analysis" $file_name
    }
  }
}

proc report_power_vcd { vcd scope {frequency_list {100.0}} } {

  set clk_name "clk"
  set rst_name "rst"

  set_cmd_units -time ns

  global sta_report_default_digits
  set corner [sta::parse_corner "-digits $sta_report_default_digits"]

  foreach frequency $frequency_list {
    set period [expr 1000.0 / $frequency]

    create_clock -name $clk_name -period $period [get_ports $clk_name]
    set_propagated_clock [get_clocks $clk_name]

    puts "clk_frequency  = $frequency (T=$period)"
    puts "VCD file       = $vcd"

    read_power_activities -scope $scope -vcd $vcd

    # Report power to the log
    report_power

    # Report power to a JSON file
    set report [sta::design_power $corner]
    set report [extract_power_report_data $report]

    set f_mhz [expr int($frequency)]

    set file_name "$::env(RESULTS_DIR)/power_analysis_vcd_f${f_mhz}.json"
    write_power_report_json $frequency {"vcd"} $report "analysis" $file_name
  }
}
