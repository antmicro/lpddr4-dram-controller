# Copyright (c) 2023-2024 Antmicro <www.antmicro.com>
# SPDX-License-Identifier: Apache-2.0

import random

import pyuvm
from pyuvm import *

from common import BusRandomWriteItem, WaitItem
from testbench import BaseEnv, BaseTest

from dfi_scoreboard import WriteScoreboard

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
