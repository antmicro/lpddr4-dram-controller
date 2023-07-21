# Copyright (c) 2023
# SPDX-License-Identifier: Apache-2.0

import random

import pyuvm
from pyuvm import *

from testbench import BusRandomWriteItem, WaitItem
from testbench import BaseEnv, BaseTest

# =============================================================================


class RandomWriteSeq(uvm_sequence):
    """
    A sequence of random write requests
    """

    def __init__(self, name):
        super().__init__(name)
        self.cfg = {
            "min_address":  0x00000000,
            "max_address":  0x00FFFFFC,
            "count":        1024,
        }

    def configure(self, cfg):
        self.cfg.update(cfg)

    async def body(self):

        # Random writes
        for i in range(self.cfg["count"]):
            item = BusRandomWriteItem((
                self.cfg["min_address"],
                self.cfg["max_address"],
            ))
            await self.start_item(item)
            item.randomize()
            await self.finish_item(item)


class SequentialWriteSeq(uvm_sequence):
    """
    A sequence of consecutive addresses (sequential) write requests
    """

    def __init__(self, name):
        super().__init__(name)
        self.cfg = {
            "address":  0x00000000,
            "step":     4,
            "count":    1024,
        }

    def configure(self, cfg):
        self.cfg.update(cfg)

    async def body(self):

        # Sequential write burst
        for i in range(self.cfg["count"]):
            addr = self.cfg["address"] + i * self.cfg["step"]
            item = BusRandomWriteItem((addr, addr))
            await self.start_item(item)
            item.randomize()
            await self.finish_item(item)


class BurstWriteSeq(uvm_sequence):
    """
    A "meta sequence" for burst writes. Generates sequential bursts separated
    by idle gaps.
    """

    def __init__(self, name):
        super().__init__(name)
        self.cfg = {
            "min_address":  0x00000000,
            "max_address":  0x00FFFFFC,
            "burst_length": 128,
            "burst_count":  10,
            "burst_gap":    500, # (cycles)
        }

    def configure(self, cfg):
        self.cfg.update(cfg)

    async def body(self):

        seqr = ConfigDB().get(None, "", "SEQR")

        # Bursts
        for j in range(self.cfg["burst_count"]):

            # Randomize burst starting address
            min_address = self.cfg["min_address"]
            max_address = self.cfg["max_address"] - 4 * self.cfg["burst_length"]
            base_addr   = random.randint(min_address, max_address) & ~0x3

            # Execute the burst
            seq = SequentialWriteSeq("random")
            seq.configure({
                "address":  base_addr,
                "count":    self.cfg["burst_length"],
            })
            await seq.start(seqr)

            # Wait
            item = WaitItem(self.cfg["burst_gap"])
            await self.start_item(item)
            await self.finish_item(item)

# =============================================================================

class WriteScoreboard(uvm_component):
    """
    Scoreboard for DRAM write test. Analyzes Wishbone write requests and DFI
    activity. Predicts (computes) DRAM addresses and checks if data written
    through Wishbone matches data written to DRAM
    """

    def __init__(self, name, parent):
        super().__init__(name, parent)
        self.passed = True

    def build_phase(self):
        self.bus_fifo   = uvm_tlm_analysis_fifo("bus_fifo", self)
        self.dfi_fifo   = uvm_tlm_analysis_fifo("dfi_fifo", self)

        self.bus_port   = uvm_get_port("bus_port", self)
        self.dfi_port   = uvm_get_port("dfi_port", self)

    def connect_phase(self):
        self.bus_port.connect(self.bus_fifo.get_export)
        self.dfi_port.connect(self.dfi_fifo.get_export)

    def check_phase(self):

        while self.bus_port.can_get():

            # Get items
            got_bus, bus_item = self.bus_port.try_get()
            got_dfi, dfi_item = self.dfi_port.try_get()

            if not got_dfi:
                self.logger.critical("No DFI read/write for for DRAM command")
                passed = False
                continue

            # Get data word being written
            if dfi_item.mask == 0x0F:
                nibble = 1
            elif dfi_item.mask == 0xF0:
                nibble = 0
            else:
                # TODO: Its not strictly invalid but shouldn't happen in this
                # controller configuration/
                self.logger.critical("Invalid DFI data mask 0x{:02X}".format(dfi_item.mask))
                self.passed = False
                continue

            # Build DRAM address
            # TODO: Parametrize / extract this data somehow
            row_nb = 13
            col_nb = 10
            bank_nb = 3

            row_mask  = (1 << row_nb ) - 1
            col_mask  = (1 << col_nb ) - 1
            bank_mask = (1 << bank_nb) - 1

            row  = dfi_item.row  & row_mask
            col  = dfi_item.col  & col_mask
            bank = dfi_item.bank & bank_mask

            dram_addr = (((row  << (1 + col_nb + bank_nb)) | \
                          (bank << (1 + col_nb)) | \
                          (col  << (1))) >> 3) | \
                           nibble

            dram_data = (dfi_item.data >> (32 * nibble)) & 0xFFFFFFFF

            msg = "bus={:08X}:{:08X} vs. dfi={:08X}:{:08X}, bank={} row=0x{:04X} col=0x:{:04X} mask=0x{:02X}".format(
                bus_item.addr,
                bus_item.data,
                dram_addr,
                dram_data,
                dfi_item.bank,
                dfi_item.row,
                dfi_item.col,
                dfi_item.mask,
            )

            # Check
            if dram_addr == bus_item.addr and dram_data == bus_item.data:
                self.logger.debug(msg)
            else:
                self.logger.error(msg)
                self.passed = False

    def final_phase(self):
        if not self.passed:
            self.logger.critical("{} reports a failure".format(type(self)))
            assert False

# =============================================================================


class TestWriteEnv(BaseEnv):
    """
    Test environment, adds the scoreboard.
    """

    def build_phase(self):
        super().build_phase()

        # Scoreboard
        self.write_scoreboard = WriteScoreboard("write_scoreboard", self)

        # Set sequencer to be used by write sequences
        ConfigDB().set(None, "*", "SEQR", self.wb_data_seqr);

    def connect_phase(self):
        super().connect_phase()

        # Scoreboard
        self.wb_data_mon.ap.connect(self.write_scoreboard.bus_fifo.analysis_export)
        self.dfi_mon.ap.connect(self.write_scoreboard.dfi_fifo.analysis_export)

# =============================================================================


@pyuvm.test()
class TestRandomWrite(BaseTest):
    """
    Performs a sequence of random memory writes
    """

    def __init__(self, name, parent):
        super().__init__(name, parent, TestWriteEnv)

    def end_of_elaboration_phase(self):
        super().end_of_elaboration_phase()
        self.seq = RandomWriteSeq.create("write")

    async def run(self):
        await self.seq.start(self.env.wb_data_seqr)


@pyuvm.test()
class TestSequentialWrite(BaseTest):
    """
    Performs a single sequential memory write
    """

    def __init__(self, name, parent):
        super().__init__(name, parent, TestWriteEnv)

    def end_of_elaboration_phase(self):
        super().end_of_elaboration_phase()
        self.seq = SequentialWriteSeq.create("write")

    async def run(self):
        await self.seq.start(self.env.wb_data_seqr)


@pyuvm.test()
class TestBurstWrite(BaseTest):
    """
    Performs a sequence of random memory sequentual write bursts
    """

    def __init__(self, name, parent):
        super().__init__(name, parent, TestWriteEnv)

    def end_of_elaboration_phase(self):
        super().end_of_elaboration_phase()
        self.seq = BurstWriteSeq.create("write")

    async def run(self):
        await self.seq.start(self.env.wb_data_seqr)
