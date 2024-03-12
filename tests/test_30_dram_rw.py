# Copyright (c) 2023-2024 Antmicro <www.antmicro.com>
# SPDX-License-Identifier: Apache-2.0

"""
Combined DRAM read/write tests
"""

import random

import pyuvm
from pyuvm import *

from common import BusReadItem, BusRandomReadItem, \
                   BusWriteItem, BusRandomWriteItem
from testbench import BaseEnv, BaseTest

from dfi_scoreboard import ReadScoreboard, WriteScoreboard

# =============================================================================


class RandomReadWriteSeq(uvm_sequence):
    """
    Random sequence of interleaved reads and writes. The class generates
    write and read requests for Wishbone bus. Reads are generated only for
    addresses previously written to.
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

    def randomize(self):

        # Generate a list of non-repeating addresses
        addrs = set()
        for i in range(self.cfg["count"]):

            # FIXME: This will loop forever if address range is smaller than
            # the count.
            while True:
                addr = random.randint(
                   self.cfg["min_address"],
                   self.cfg["max_address"]
                ) & ~0x3

                if addr not in addrs:
                    addrs.add(addr)
                    break

        addrs = list(addrs)

        # Generate the sequence. Randomize operation, then randomize the
        # address. Randomize read addresses from the set of previously
        # written ones. No repetitions
        self.seq = []
        written  = set()

        idx = 0
        while idx < len(addrs) or len(written):

            rd = random.choice([False, True])

            # FIXME: This is suboptimal as if one of the while loop conditions
            # is not satisfied then there is only 50% chance of hitting one
            # of the if conditions below. Not critical though.

            # Read
            if rd and len(written):
                addr = random.choice(list(written))
                written.discard(addr)

                self.seq.append(("RD", addr,))

            # Write
            elif not rd and idx < len(addrs):
                addr = addrs[idx]
                written.add(addr)
                idx += 1

                self.seq.append(("WR", addr,))

    async def body(self):

        for op, addr in self.seq:

            if op == "RD":
                item = BusReadItem(addr)
            elif op == "WR":
                item = BusRandomWriteItem((addr, addr))
            else:
                assert False

            await self.start_item(item)
            item.randomize()
            await self.finish_item(item)

# =============================================================================


class ReadWriteScoreboard(uvm_component):
    """
    A scoreboard for DRAM read/write tests. Analyzes Wishbone transactions,
    stores written data internally and compares it with data read through the
    bus from DRAM
    """

    def __init__(self, name, parent):
        super().__init__(name, parent)
        self.passed = None

    def build_phase(self):
        self.fifo = uvm_tlm_analysis_fifo("fifo", self)
        self.port = uvm_get_port("port", self)

    def connect_phase(self):
        self.port.connect(self.fifo.get_export)

    def check_phase(self):

        storage  = dict()

        total    = 0
        mismatch = 0

        # Analyze transactions
        while self.port.can_get():
            _, item = self.port.try_get()

            # Initially pass
            if self.passed is None:
                self.passed = True

            # Write
            if isinstance(item, BusWriteItem) or isinstance(item, BusRandomWriteItem):
                storage[item.addr] = int(item.data)

            # Read
            if isinstance(item, BusReadItem) or isinstance(item, BusRandomReadItem):
                data   = storage.get(item.addr, None)
                total += 1

                if data is None:
                    mismatch += 1
                    self.logger.error("No previous write to 0x{:08X}", item.addr)
                    self.passed = False

                elif data != int(item.data):
                    mismatch += 1
                    self.logger.error("Mismatch at 0x{:08X}, written 0x{:08X}, read 0x{:08X}".format(
                        item.addr, data, int(item.data)))
                    self.passed = False

        self.logger.info("{} / {} mismatches".format(mismatch, total))

    def final_phase(self):
        if not self.passed:
            self.logger.critical("{} reports a failure".format(type(self)))
            assert False

# =============================================================================


class TestReadWriteEnv(BaseEnv):
    """
    Test environment, adds the scoreboard.
    """

    def __init__(self, name, parent):
        super().__init__(name, parent)

        ConfigDB().set(None, "*", "DRAM_STORAGE", True);

    def build_phase(self):
        super().build_phase()

        # Scoreboards
        self.read_scoreboard  = ReadScoreboard("read_scoreboard", self)
        self.write_scoreboard = WriteScoreboard("write_scoreboard", self)
        self.rw_scoreboard    = ReadWriteScoreboard("rw_scoreboard", self)

        # Set sequencer to be used by read sequences
        ConfigDB().set(None, "*", "SEQR", self.wb_data_seqr)

    def connect_phase(self):
        super().connect_phase()

        # Scoreboards
        self.wb_data_mon.ap.connect(self.read_scoreboard.bus_fifo.analysis_export)
        self.dfi_mon.ap.connect(self.read_scoreboard.dfi_fifo.analysis_export)

        self.wb_data_mon.ap.connect(self.write_scoreboard.bus_fifo.analysis_export)
        self.dfi_mon.ap.connect(self.write_scoreboard.dfi_fifo.analysis_export)

        self.wb_data_mon.ap.connect(self.rw_scoreboard.fifo.analysis_export)

# =============================================================================


@pyuvm.test()
class TestRandomReadWrite(BaseTest):
    """
    Performs a sequence of random memory reads and writes
    """

    def __init__(self, name, parent):
        super().__init__(name, parent, TestReadWriteEnv)

    def end_of_elaboration_phase(self):
        super().end_of_elaboration_phase()
        self.seq = RandomReadWriteSeq.create("rw")
        self.seq.randomize()

    async def run(self):
        await self.seq.start(self.env.wb_data_seqr)
