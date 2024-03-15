# report_power gcd

puts "---------------------------"
puts "DRAM Controller"
puts "Custom power OpenSTA Script"
puts "---------------------------"


# From opensta/examples
# read_liberty sky130hd_tt.lib
# read_verilog gcd_sky130hd.v
# link_design gcd
# read_sdc gcd_sky130hd.sdc
# set_propagated_clock clk
# read_spef gcd_sky130hd.spef
# set_power_activity -input -activity .1
# set_power_activity -input_port reset -activity 0
# report_power

proc report_power_custom {} {
puts "\n=========================================================================="
  set activity_list {0.0 1.0 2.0}
  set clk_periods {10 1000}

  foreach clk_period $clk_periods {
    create_clock -name clk -period $clk_period {clk}
    set_input_delay -clock clk 0 {d1 d2}

    foreach activity_level $activity_list {
        puts "clk_period = $clk_period"
        puts "activity_level = $activity_level"
        set_power_activity -input -activity $activity_level
        set_power_activity -input_port rst -activity 0
        report_power
    }
  }
}

