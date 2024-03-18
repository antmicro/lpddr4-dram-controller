# Copyright (c) 2023 Antmicro <www.antmicro.com>
# SPDX-License-Identifier: Apache-2.0

null  :=
space := $(null) #
comma := ,

TEST_FILES       = $(sort $(wildcard test_*.py))
MODULE          ?= $(subst $(space),$(comma),$(subst .py,,$(TEST_FILES)))
TOPLEVEL         = dram_ctrl
TOPLEVEL_LANG    = verilog
BUILD_DIR       ?= ../build/$(TOPLEVEL)

VERILOG_SOURCES ?= $(BUILD_DIR)/gateware/dram_ctrl.v
export CSR_CSV   = $(BUILD_DIR)/csr.csv

SIM             ?= verilator
WAVES           ?= 1

# Enable processing of #delay statements
ifeq ($(SIM), verilator)
    COMPILE_ARGS += --timing
    COMPILE_ARGS += -Wno-WIDTHEXPAND
    COMPILE_ARGS += -Wno-WIDTHTRUNC
    COMPILE_ARGS += -Wno-CASEINCOMPLETE
    COMPILE_ARGS += -Wno-CMPCONST
    COMPILE_ARGS += -Wno-fatal

    EXTRA_ARGS   += --trace --trace-structs --trace-underscore
endif

COCOTB_HDL_TIMEUNIT         = 1ns
COCOTB_HDL_TIMEPRECISION    = 10ps

include $(shell cocotb-config --makefiles)/Makefile.sim
