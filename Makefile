# Copyright 2023 Antmicro <www.antmicro.com>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


SHELL=/bin/bash

ROOT_DIR=$(CURDIR)
PROJ?=dram_ctrl
BUILD_DIR=$(ROOT_DIR)/build/$(PROJ)
TEST_DIR=$(ROOT_DIR)/tests
SRC_DIR=$(ROOT_DIR)/src
THIRD_PARTY_DIR=$(ROOT_DIR)/third_party
TP_ORFS_DIR=$(THIRD_PARTY_DIR)/OpenROAD-flow-scripts
CONFIG?=$(SRC_DIR)/standalone-dfi.yml
PDK?=sky130hd
GDS=$(TP_ORFS_DIR)/flow/results/$(PDK)/$(PROJ)/base/6_final.gds
YOSYS_CMD?=$(shell command -v yosys)
OPENROAD_EXE?=$(shell command -v openroad)

# Include ORFS Makefile
# include $(TP_ORFS_DIR)/flow/Makefile

# Export variables for ASIC flow
export PROJ
export ROOT_DIR
export YOSYS_CMD
export OPENROAD_EXE

# Determine verilog top file path based on project name
ifeq '$(PROJ)' 'ander'
VERILOG_TOP=$(ROOT_DIR)/ander/ander.sv
else ifeq '$(PROJ)' 'dram_ctrl'
VERILOG_TOP=$(BUILD_DIR)/gateware/$(PROJ).v
else ifeq '$(VERILOG_TOP)' ''
$(error Uknown project '$(PROJ)', please set 'VERILOG_TOP' to the verilog top file path)
endif

verilog: $(VERILOG_TOP) ## Generate verilog sources

$(VERILOG_TOP):
	python3 $(ROOT_DIR)/gen.py $(CONFIG) --output-dir $(BUILD_DIR) --name $(PROJ)

tests: $(VERILOG_TOP) ## Run tests in Verilator
	$(MAKE) -C $(TEST_DIR) sim BUILD_DIR=$(BUILD_DIR)

asic: $(GDS) ## Run ASIC flow

$(GDS): $(VERILOG_TOP)
	$(MAKE) -C $(TP_ORFS_DIR)/flow DESIGN_CONFIG=$(ROOT_DIR)/openroad/${PROJ}/configs/${PDK}/config.mk

drc: $(GDS) ## Run DRC phase for generated ASIC
	$(MAKE) -C $(TP_ORFS_DIR)/flow DESIGN_CONFIG=$(ROOT_DIR)/openroad/${PROJ}/configs/${PDK}/config.mk drc

lvs: $(GDS) ## Run LVS phase for generated ASIC
	$(MAKE) -C $(TP_ORFS_DIR)/flow DESIGN_CONFIG=$(ROOT_DIR)/openroad/${PROJ}/configs/${PDK}/config.mk lvs

power-analysis:
	bash opensta/run_sta.sh

clean: ## Remove generated verilog sources
	$(RM) -r $(BUILD_DIR)

clean-asic: ## Remove generated ASIC files
	$(RM) -r $(TP_ORFS_DIR)/flow/logs/$(PDK)/$(PROJ)
	$(RM) -r $(TP_ORFS_DIR)/flow/results/$(PDK)/$(PROJ)
	$(RM) -r $(TP_ORFS_DIR)/flow/objects/$(PDK)/$(PROJ)
	$(RM) -r $(TP_ORFS_DIR)/flow/reports/$(PDK)/$(PROJ)

.PHONY: clean clean-asic verilog tests asic asic-drc asic-lvs



.DEFAULT_GOAL := help
HELP_COLUMN_SPAN = 10
HELP_FORMAT_STRING = "\033[36m%-$(HELP_COLUMN_SPAN)s\033[0m %s\n"
help: ## Show this help message
	@echo List of available targets:
	@grep -hE '^[^#[:blank:]]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf $(HELP_FORMAT_STRING), $$1, $$2}'
	@echo
	@echo
	@echo List of available optional parameters:
	@echo
	@echo -e "\033[36mCONFIG\033[0m     Path to controller configuration file (default: '$(CONFIG)')"
	@echo -e "\033[36mPROJ\033[0m       Top module design name (default: '$(PROJ)')"
	@echo -e "\033[36mPDK\033[0m        Name of Physical Design Kit for ASIC flow (default: '$(PDK)')"
