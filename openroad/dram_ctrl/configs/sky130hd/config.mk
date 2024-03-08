export DESIGN_NICKNAME  = $(PROJ)
export DESIGN_NAME      = $(PROJ)
export PLATFORM         = sky130hd

export VERILOG_FILES    = $(ROOT_DIR)/build/$(PROJ)/gateware/dram_ctrl.v
export SDC_FILE         = $(ROOT_DIR)/openroad/$(PROJ)/configs/$(PLATFORM)/constraints.sdc

export CORE_UTILIZATION = 40
export PLACE_DENSITY    = 0.6
export TNS_END_PERCENT  = 100
