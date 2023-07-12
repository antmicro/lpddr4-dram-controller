export DESIGN_NICKNAME  = dram_ctrl
export DESIGN_NAME      = dram_ctrl
export PLATFORM         = asap7

export VERILOG_FILES    = ../../build/gateware/dram_ctrl.v
export SDC_FILE         = ../../openroad/configs/$(PLATFORM)/constraints.sdc

export CORE_UTILIZATION = 40
export PLACE_DENSITY    = 0.61
export TNS_END_PERCENT  = 100
