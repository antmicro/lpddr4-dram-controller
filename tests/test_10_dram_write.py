# Copyright (c) 2023
# SPDX-License-Identifier: Apache-2.0

import random

import pyuvm
from pyuvm import *

from testbench import BusRandomWriteItem, WaitItem
from testbench import BaseEnv, BaseTest

from dfi_scoreboard import DFIScoreboard

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

class WriteScoreboard(DFIScoreboard):
    """
    Scoreboard for DRAM write test. Analyzes Wishbone write requests and DFI
    activity. Predicts (computes) DRAM addresses and checks if data written
    through Wishbone matches data written to DRAM
    """

    def check_phase(self):

        while self.bus_port.can_get():

            # Get items
            got_bus, bus_item = self.bus_port.try_get()
            got_dfi, dfi_item = self.dfi_port.try_get()

            if not got_dfi:
                self.logger.critical("No DFI read/write for for DRAM command")
                self.passed = False
                continue

            # Check items
            check = True

            if bus_item.data.n_bits not in [32]:
                self.logger.critical("Unsupported bus data width {}",
                    bus_item.data.n_bits
                )
                check = False

            if dfi_item.data.n_bits not in [32, 64]:
                self.logger.critical("Unsupported DFI data width {}",
                    dfi_item.data.n_bits
                )
                check = False

            ratio = dfi_item.data.n_bits / bus_item.data.n_bits
            if ratio  not in [1.0, 2.0, 4.0]:
                self.logger.critical("Unsupported bus to DFI data ratio")
                check = False

            # Get data word being written
            if dfi_item.data.n_bits == 64:
                if dfi_item.mask == 0x0F:
                    word = 1
                elif dfi_item.mask == 0xF0:
                    word = 0
                else:
                    # TODO: Its not strictly invalid but shouldn't happen.
                    self.logger.critical(
                        "Invalid DFI data mask 0x{:02X}".format(
                            dfi_item.mask.integer
                        )
                    )
                    check = False

            elif dfi_item.data.n_bits == 32:
                if dfi_item.mask == 0x0:
                    word = 0
                else:
                    # TODO: Its not strictly invalid but shouldn't happen.
                    self.logger.critical(
                        "Invalid DFI data mask 0x{:01X}".format(
                            dfi_item.mask.integer
                        )
                    )
                    check = False

            else:
                # Shouldn't happen
                assert False

            # Failure
            if not check:
                self.passed = False
                continue

            # Build DRAM address
            dram_addr  = self.decode_dram_address(dfi_item) >> (3 - (int)(ratio - 1))
            dram_addr |= word
            dram_data  = (dfi_item.data >> (32 * word)) & 0xFFFFFFFF

            msg = "bus={:08X}:{:08X} vs. dfi={:08X}:{:08X}, bank={} row=0x{:04X} col=0x:{:04X} mask=0x{:02X}".format(
                bus_item.addr,
                int(bus_item.data),
                dram_addr,
                dram_data,
                dfi_item.bank,
                dfi_item.row,
                dfi_item.col,
                int(dfi_item.mask),
            )

            # Check
            if dram_addr == bus_item.addr and dram_data == int(bus_item.data):
                self.logger.debug(msg)
            else:
                self.logger.error(msg)
                self.passed = False

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
