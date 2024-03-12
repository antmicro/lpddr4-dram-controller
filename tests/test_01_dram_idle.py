# Copyright (c) 2023-2024 Antmicro <www.antmicro.com>
# SPDX-License-Identifier: Apache-2.0

import pyuvm
from pyuvm import uvm_sequence

from common import WaitItem
from testbench import BaseTest

# =============================================================================

class IdleSeq(uvm_sequence):
    """
    A dummy sequence that emits a single WaitItem to make the simulation run
    for a while.
    """

    async def body(self):

        # Wait
        item = WaitItem(10000) # FIXME: Arbitrary
        await self.start_item(item)
        await self.finish_item(item)

@pyuvm.test()
class TestDramIdle(BaseTest):
    """
    Tests the behavior of the controller when no operations are issued
    to the DRAM
    """

    def end_of_elaboration_phase(self):
        super().end_of_elaboration_phase()
        self.idle_seq = IdleSeq.create("idle_seq")

    async def run(self):

        await self.idle_seq.start(self.env.wb_ctrl_seqr)
