import random

import pyuvm
from pyuvm import *

from testbench import BusRandomReadItem, WaitItem
from testbench import BaseEnv, BaseTest

from dfi_scoreboard import DFIScoreboard

# =============================================================================


class RandomReadSeq(uvm_sequence):

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

        # Random reads
        for i in range(self.cfg["count"]):
            item = BusRandomReadItem((
                self.cfg["min_address"],
                self.cfg["max_address"],
            ))
            await self.start_item(item)
            item.randomize()
            await self.finish_item(item)


# =============================================================================

class ReadScoreboard(DFIScoreboard):

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
            # FIXME: Support bus to DFI width ratio
            if bus_item.data.n_bits != dfi_item.data.n_bits:
                self.logger.critical("Bus data width must be equal to DFI data width")
                self.passed = False
                continue

            # Build DRAM address
            dram_addr = self.decode_dram_address(dfi_item) >> 3

            # Check
            msg = "bus={:08X}:{:08X} vs. dfi={:08X}:{:08X}, bank={} row=0x{:04X} col=0x:{:04X}".format(
                bus_item.addr,
                int(bus_item.data),
                dram_addr,
                int(dfi_item.data),
                dfi_item.bank,
                dfi_item.row,
                dfi_item.col
            )

            if dram_addr == bus_item.addr and int(dfi_item.data) == int(bus_item.data):
                self.logger.debug(msg)
            else:
                self.logger.error(msg)
                self.passed = False

# =============================================================================


class TestReadEnv(BaseEnv):
    """
    Test environment, adds the scoreboard.
    """

    def build_phase(self):
        super().build_phase()

        # Scoreboard
        self.read_scoreboard = ReadScoreboard("read_scoreboard", self)

        # Set sequencer to be used by read sequences
        ConfigDB().set(None, "*", "SEQR", self.wb_data_seqr);

    def connect_phase(self):
        super().connect_phase()

        # Scoreboard
        self.wb_data_mon.ap.connect(self.read_scoreboard.bus_fifo.analysis_export)
        self.dfi_mon.ap.connect(self.read_scoreboard.dfi_fifo.analysis_export)

# =============================================================================


@pyuvm.test()
class TestRandomRead(BaseTest):
    """
    Performs a sequence of random memory reads
    """

    def __init__(self, name, parent):
        super().__init__(name, parent, TestReadEnv)

    def end_of_elaboration_phase(self):
        super().end_of_elaboration_phase()
        self.seq = RandomReadSeq.create("read")

    async def run(self):
        await self.seq.start(self.env.wb_data_seqr)
