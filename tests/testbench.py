# Copyright (c) 2023-2024 Antmicro <www.antmicro.com>
# SPDX-License-Identifier: Apache-2.0

"""
Main testbench module for the DRAM controller. Provides various utilities and
pyuvm components used by the tests.
"""

import pyuvm
from pyuvm import *

from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge

import os
import logging

from common import BusReadItem, BusRandomReadItem, DRAMReadItem, \
                   BusWriteItem, BusRandomWriteItem, WaitItem

from dram_model import Model, Timings
from csr import load_csrs

# =============================================================================

class WishboneInterface:
    """
    Wishbone interface "low-level" handler, a.k.a. BFM
    """

    SIGNALS = [
        "adr",
        "dat_w",
        "dat_r",
        "sel",
        "cyc",
        "stb",
        "ack",
        "we",
        "err",
    ]

    def __init__(self, uut, clk, pfx=""):

        # Collect Wishbone signals
        for sig in self.SIGNALS:
            prefixed = pfx + sig
            if hasattr(uut, prefixed):
                obj = getattr(uut, prefixed)
            else:
                obj = None
                logging.err("Module {} does not have a signal '{}'",
                    str(uut),
                    prefixed
                )
            setattr(self, "wb_" + sig, obj)

        # Get the clock
        obj = getattr(uut, clk)
        setattr(self, "wb_clk", obj)

        # Internals
        self.timeout_cycles = 100 # FIXME: Arbitrary

    async def write(self, addr, data):
        """
        Single 32-bit write
        """

        await RisingEdge(self.wb_clk)

        self.wb_adr.value   = addr >> 2
        self.wb_dat_w.value = data
        self.wb_sel.value   = 0xF
        self.wb_cyc.value   = 1
        self.wb_stb.value   = 1
        self.wb_we.value    = 1

        for i in range(self.timeout_cycles):
            await RisingEdge(self.wb_clk)
            if self.wb_ack.value == 1:
                break
        else:
            uvm_root().logger.critical("Wishbone bus write timeout!")
            assert False

        self.wb_sel.value   = 0
        self.wb_cyc.value   = 0
        self.wb_stb.value   = 0

    async def read(self, addr):
        """
        Single 32-bit read
        """

        await RisingEdge(self.wb_clk)

        self.wb_adr.value   = addr >> 2
        self.wb_sel.value   = 0xF
        self.wb_cyc.value   = 1
        self.wb_stb.value   = 1
        self.wb_we.value    = 0

        for i in range(self.timeout_cycles):
            await RisingEdge(self.wb_clk)
            if self.wb_ack.value == 1:
                break
        else:
            uvm_root().logger.critical("Wishbone bus read timeout!")
            assert False

        self.wb_sel.value   = 0
        self.wb_cyc.value   = 0
        self.wb_stb.value   = 0

        return self.wb_dat_r.value


class WishboneDriver(uvm_driver):
    """
    Wishbone bus driver. Receives transfers from a sequencers and execures
    them using the interface (BFM).
    """

    def __init__(self, *args, **kwargs):
        self.iface = kwargs["iface"]
        del kwargs["iface"]
        super().__init__(*args, **kwargs)

    async def run_phase(self):
        while True:
            it = await self.seq_item_port.get_next_item()

            if isinstance(it, BusWriteItem) or isinstance(it, BusRandomWriteItem):
                await self.iface.write(it.addr, it.data)
            elif isinstance(it, BusReadItem) or isinstance(it, BusRandomReadItem):
                it.data = await self.iface.read(it.addr)
            elif isinstance(it, WaitItem):
                for i in range(it.cycles):
                    await RisingEdge(self.iface.wb_clk)
            else:
                raise RuntimeError("Unknown item '{}'".format(type(it)))

            self.seq_item_port.item_done()


# =============================================================================

class DFIInterface:
    """
    DFI interface "low-level" handler, a.k.a. BFM
    """

    SIGNALS = [
        "cke",
        "odt",
        "reset_n",
        "mode_2n",
        "alert_n",

        "address",
        "bank",
        "cs_n",
        "ras_n",
        "cas_n",
        "we_n",

        "wrdata",
        "wrdata_en",
        "wrdata_mask",

        "rddata",
        "rddata_en",
        "rddata_valid",

        "init_start",
        "init_complete",
    ]

    def __init__(self, uut, clk, pfx=""):

        # Collect DFI signals
        for sig in self.SIGNALS:
            prefixed = pfx + sig
            if hasattr(uut, prefixed):
                obj = getattr(uut, prefixed)
            else:
                obj = None
                logging.err("Module {} does not have a signal '{}'",
                    str(uut),
                    prefixed
                )
            setattr(self, "dfi_" + sig, obj)

        # Get the clock
        obj = getattr(uut, clk)
        setattr(self, "dfi_clk", obj)

    async def read(self, data):
        """
        Feeds data to the DFI read interface
        """

        self.dfi_rddata.value       = data
        self.dfi_rddata_valid.value = 1

        await RisingEdge(self.dfi_clk)

        self.dfi_rddata_valid.value = 0


class DFIResponder(uvm_component):
    """
    DFI training request responder. Attatches itself to the training request /
    response port and simulates PHY training
    """

    def __init__(self, *args, **kwargs):
        self.iface = kwargs["iface"]
        del kwargs["iface"]
        super().__init__(*args, **kwargs)

        # Internals
        self.is_trained = False

    async def run(self):

        while True:

            # Wait for clock
            await RisingEdge(self.iface.dfi_clk)

            # Init request
            if self.iface.dfi_init_start.value == 1 and not self.is_trained:

                # Wait n cycles
                for i in range(100): # FIXME: Arbitrary training delay
                    await RisingEdge(self.iface.dfi_clk)

                # Pulse init_complete
                self.iface.dfi_init_complete.value = 1
                await RisingEdge(self.iface.dfi_clk)
                self.iface.dfi_init_complete.value = 0

                # Trained
                self.is_trained = True

    def start(self):
        cocotb.start_soon(self.run())


class DFIDriver(uvm_driver):
    """
    Driver for the DFI interface. Responsible for handling DRAM read
    transfers where data must be injected into DFI.
    """

    def __init__(self, *args, **kwargs):
        self.iface = kwargs["iface"]
        del kwargs["iface"]
        super().__init__(*args, **kwargs)

    async def run_phase(self):
        while True:
            it = await self.seq_item_port.get_next_item()
            assert isinstance(it, DRAMReadItem)

            # Pass the data to DFI
            await self.iface.read(it.data)

            self.seq_item_port.item_done()

# =============================================================================


class WishboneMonitor(uvm_component):
    """
    Wishbone bus monitor. Observes transactions and sends appropriate items
    through its analysis port.
    """

    def __init__(self, *args, **kwargs):
        self.iface = kwargs["iface"]
        del kwargs["iface"]
        super().__init__(*args, **kwargs)
        
    def build_phase(self):
        self.ap = uvm_analysis_port("ap", self)

    async def run_phase(self):
        while True:

            await RisingEdge(self.iface.wb_clk)

            # Transaction
            if self.iface.wb_cyc.value:
                if self.iface.wb_stb.value and self.iface.wb_ack.value:

                    addr = int(self.iface.wb_adr.value)

                    # Write
                    if self.iface.wb_we.value:
                        data = self.iface.wb_dat_w.value
                        self.logger.debug("write 0x{:08X} <- 0x{:08X}".format(addr, int(data)))
                        self.ap.write(BusWriteItem(addr, data))

                    # Read
                    else:
                        data = self.iface.wb_dat_r.value
                        self.logger.debug("read  0x{:08X} -> 0x{:08X}".format(addr, int(data)))
                        self.ap.write(BusReadItem(addr, data))


class DFIMonitor(uvm_component):
    """
    DFI monitor. Encapsulates the PHY+DRAM model.
    """

    def __init__(self, *args, **kwargs):
        self.iface = kwargs["iface"]
        del kwargs["iface"]
        super().__init__(*args, **kwargs)

        # Instantiate a PHY+DRAM model
        storage = ConfigDB().get(self, "", "DRAM_STORAGE") != 0
        self.dram = Model(self.iface, self.logger, with_storage=storage)

    def build_phase(self):
        self.ap = uvm_analysis_port("ap", self)
        self.rp = uvm_seq_item_export("rp", self)

        self.dram.ap = self.ap

    async def run_phase(self):
        while True:

            # Wait for rising edge and run the model
            await RisingEdge(self.iface.dfi_clk)
            res = await self.dram.tick()

            # If a read/write has been detected, push it to the analysis port
            # Push read requests to the read request port (rp)
            if res:
                if res[0] == "WR":
                    # Write items are being sent to the analysis port by the
                    # separate coroutine spawned inside the `self.dram.tick()`
                    pass

                elif res[0] == "RD":
                    self.ap.write(DRAMReadItem(*res[1:]))

                    # FIXME: This is a bit hacky - the monitor mimics a
                    # sequencer.
                    item = DRAMReadItem(*res[1:])
                    item.item_ready.set()
                    await self.rp.put_req(item)

                else:
                    assert False, "Unknown DFI operation '{}'".format(res)

    def final_phase(self):
        if not self.dram.passed:
            self.logger.critical("{} reports a failure".format(type(self)))
            assert False

# =============================================================================


class InitSeq(uvm_sequence):
    """
    DRAM controller initialization sequence
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.training_timeout_cycles = 200

        csr_csv = ConfigDB().get(None, "", "CSR_CSV")
        self.csrs = load_csrs(csr_csv)

    async def write(self, addr, data):
        item = BusWriteItem(addr, data)
        await self.start_item(item)
        await self.finish_item(item)

    async def read(self, addr):
        item = BusReadItem(addr)
        await self.start_item(item)
        await self.finish_item(item)
        return item.data

    async def write_csr(self, name, data):
        csr = self.csrs[name]
        await self.write(csr.address, data)

    async def read_csr(self, name):
        csr = self.csrs[name]
        return await self.read(csr.address)

    async def body(self):

        # Setup timings
        for timing in Timings.TIMINGS:
            value = int(ConfigDB().get(None, "", timing))
            csr_name = "dram_ctrl_controller_" + timing
            await self.write_csr(csr_name, value)

        # Reset the DRAM memory
        await self.write_csr("ddrphy_rst", 1)

        item = WaitItem(10) # TODO: Wait the required time
        await self.start_item(item)
        await self.finish_item(item)

        await self.write_csr("ddrphy_rst", 0)

        # Instruct the PHY to begin training
        await self.write_csr("dram_ctrl_controller_phy_ctl", 1)

        # Wait for the PHY training to complete
        for i in range(self.training_timeout_cycles):

            # Wait
            item = WaitItem(10)
            await self.start_item(item)
            await self.finish_item(item)

            # Poll
            data = await self.read_csr("dram_ctrl_controller_phy_sts")

            # Training has completed
            if data & 0x01:
                break

        else:
            uvm_root().logger.critical("PHY training timeout!")
            assert False

        # Write the status CSRs
        await self.write_csr("ddrctrl_init_done",  1)
        await self.write_csr("ddrctrl_init_error", 0)

        # Wait (dummy)
        item = WaitItem(10)
        await self.start_item(item)
        await self.finish_item(item)


# =============================================================================

class BaseEnv(uvm_env):
    """
    Base DRAM controller test environment. Includes control Wishbone, data
    Wishbone bus and DFI drivers and monitors.
    """

    def build_phase(self):
        self.wb_ctrl_seqr = uvm_sequencer("wb_ctrl_seqr", self)
        self.wb_data_seqr = uvm_sequencer("wb_data_seqr", self)

        # Control Wishbone
        iface = WishboneInterface(cocotb.top, "clk", "wb_ctrl_")
        self.wb_ctrl_driver = WishboneDriver("wb_ctrl_drv", self, iface=iface)
        self.wb_ctrl_mon    = WishboneMonitor("wb_ctrl_mon", self, iface=iface)

        # Data wishbone
        iface = WishboneInterface(cocotb.top, "clk", "user_port_wishbone_0_")
        self.wb_data_driver = WishboneDriver("wb_data_drv", self, iface=iface)
        self.wb_data_mon    = WishboneMonitor("wb_data_mon", self, iface=iface)

        # DFI
        iface = DFIInterface(cocotb.top, "clk", "dfi_")
        self.dfi_responder  = DFIResponder("dfi_rsp", self, iface=iface)
        self.dfi_driver     = DFIDriver("dfi_drv", self, iface=iface)
        self.dfi_mon        = DFIMonitor("dfi_mon", self, iface=iface)

    def connect_phase(self):
        self.wb_ctrl_driver.seq_item_port.connect(self.wb_ctrl_seqr.seq_item_export)
        self.wb_data_driver.seq_item_port.connect(self.wb_data_seqr.seq_item_export)
        self.dfi_driver.seq_item_port.connect(self.dfi_mon.rp)

# =============================================================================


class BaseTest(uvm_test):
    """
    Base controller test class. Performs the controller initialization.
    """

    def __init__(self, name, parent, env_class=BaseEnv):
        super().__init__(name, parent)
        self.env_class = env_class

        # Syncrhonize pyuvm logging level with cocotb logging level. Unclear
        # why it does not happen automatically.
        level = logging.getLevelName(os.environ.get("COCOTB_LOG_LEVEL", "INFO"))
        uvm_report_object.set_default_logging_level(level)

        # Load the config
        db = ConfigDB()
        db.set(None, "*", "CSR_CSV",  os.environ.get("CSR_CSV", "csr.csv"))
        db.set(None, "*", "CLK_FREQ", 100.0)

        db.set(None, "*", "CL",       3)
        db.set(None, "*", "WR_LAT",   3)

        db.set(None, "*", "tRP",      2)
        db.set(None, "*", "tRCD",     2)
        db.set(None, "*", "tWR",      2)
        db.set(None, "*", "tWTR",     2)
        db.set(None, "*", "tREFI",    586)
        db.set(None, "*", "tRFC",     16)
        db.set(None, "*", "tFAW",     5)
        db.set(None, "*", "tCCD",     1)
        db.set(None, "*", "tRRD",     2)
        db.set(None, "*", "tRC",      5)
        db.set(None, "*", "tRAS",     4)
        db.set(None, "*", "tZQCS",    16)

        # Disable DRAM storage simulation by default
        ConfigDB().set(None, "*", "DRAM_STORAGE", False);

    def build_phase(self):
        self.env = self.env_class("env", self)

    def end_of_elaboration_phase(self):
        self.init_seq = InitSeq.create("init_seq")

    def start_clock(self):
        freq  = float(ConfigDB().get(self, "", "CLK_FREQ"))
        clock = Clock(cocotb.top.clk, int(1000.0 / freq + 0.5), units="ns")
        cocotb.start_soon(clock.start(start_high=False))

    async def do_reset(self):
        cocotb.top.rst.value = 1
        for i in range(5):
            await RisingEdge(cocotb.top.clk)
        await FallingEdge(cocotb.top.clk)
        cocotb.top.rst.value = 0

    async def run_phase(self):
        self.raise_objection()

        # Start the clock
        self.start_clock()

        # Start DFI responder
        self.env.dfi_responder.start()

        # Issue a reset pulse
        await self.do_reset()

        # Initialize the controller
        await self.init_seq.start(self.env.wb_ctrl_seqr)

        # Check if the controller is initialized
        if cocotb.top.init_done.value != 1:
            uvm_root().logger.critical("The controller did not initialize")
            assert False

        if cocotb.top.init_error.value != 0:
            uvm_root().logger.critical("The controller reported initialization error")
            assert False

        # Run the actual test
        await self.run()

        # Wait a number of clock cycles
        for i in range(100):
            await RisingEdge(cocotb.top.clk)

        self.drop_objection()

    async def run(self):
        raise NotImplementedError()

# =============================================================================
