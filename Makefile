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

ROOT=$(CURDIR)
PROJ?=dram_ctrl
BUILD_DIR=$(ROOT)/build/$(PROJ)
TEST_DIR=$(ROOT)/tests
SRC_DIR=$(ROOT)/src
VERILOG_TOP=$(BUILD_DIR)/gateware/$(PROJ).v
CONFIG?=$(SRC_DIR)/standalone-dfi.yml


verilog: $(VERILOG_TOP) ## Generate verilog sources

$(VERILOG_TOP):
	python3 $(ROOT)/gen.py $(CONFIG) --output-dir $(BUILD_DIR) --name $(PROJ)

tests: $(VERILOG_TOP) ## Run tests in Verilator
	$(MAKE) -C $(TEST_DIR) sim BUILD_DIR=$(BUILD_DIR)

clean:
	$(RM) -r $(BUILD_DIR)

.PHONY: clean verilog tests

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
