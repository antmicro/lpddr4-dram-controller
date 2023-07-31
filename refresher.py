# Copyright (c) 2016-2019 Florent Kermarrec <florent@enjoy-digital.fr>
# Copyright (c) 2015 Sebastien Bourdeauducq <sb@m-labs.hk>
# Copyright (c) 2023 Antmicro <www.antmicro.com>
# SPDX-License-Identifier: BSD-2-Clause

"""DRAM Refresher."""

from migen import *
from litex.soc.interconnect import stream
from litedram.common import TimelineCounter

from multiplexer import cmd_request_rw_layout

# RefreshExecutor ----------------------------------------------------------------------------------

class RefreshExecutor(Module):
    """Refresh Executor

    Execute the refresh sequence to the DRAM:
    - Send a "Precharge All" command
    - Wait tRP
    - Send an "Auto Refresh" command
    - Wait tRFC
    """
    def __init__(self, cmd, trp, trfc):
        self.start = Signal()
        self.done  = Signal()

        # # #

        tlc = TimelineCounter(max(trp.nbits, trfc.nbits) + 1)
        self.submodules += tlc
        trp_max_val = 0
        trfc_max_val = 0
        if isinstance(trp, int):
            trp_max_val = trp
        else:
            trp_max_val = 2**trp.nbits

        if isinstance(trfc, int):
            trfc_max_val = trfc
        else:
            trfc_max_val = 2**trfc.nbits

        counter = Signal(max=trp_max_val+trfc_max_val)
        self.sync += counter.eq(trp+trfc)

        self.comb += [
            tlc.trigger.eq(self.start),
            tlc.target.eq(counter),
        ]

        self.sync += [
            cmd.a.eq(  0),
            cmd.ba.eq( 0),
            cmd.cas.eq(0),
            cmd.ras.eq(0),
            cmd.we.eq( 0),
            self.done.eq(0),
        ]
        self.sync += [
            If(tlc.trigger & (tlc.counter == 0),
                cmd.a.eq(  2**10),
                cmd.ba.eq( 0),
                cmd.cas.eq(0),
                cmd.ras.eq(1),
                cmd.we.eq( 1)
            ),
            If(tlc.counter == trp,
                cmd.a.eq(  2**10),  # all banks in LPDDR4/DDR5, ignored in other memories
                cmd.ba.eq( 0),
                cmd.cas.eq(1),
                cmd.ras.eq(1),
                cmd.we.eq( 0),
            ),
            If(tlc.counter == (trp + trfc),
                cmd.a.eq(  0),  # all banks in LPDDR4/DDR5, ignored in other memories
                cmd.ba.eq( 0),
                cmd.cas.eq(0),
                cmd.ras.eq(0),
                cmd.we.eq( 0),
                self.done.eq(1),
            )
        ]

# RefreshSequencer ---------------------------------------------------------------------------------

class RefreshSequencer(Module):
    """Refresh Sequencer

    Sequence N refreshs to the DRAM.
    """
    def __init__(self, cmd, trp, trfc, postponing=1):
        self.start = Signal()
        self.done  = Signal()

        # # #

        executor = RefreshExecutor(cmd, trp, trfc)
        self.submodules += executor

        count = Signal(bits_for(postponing), reset=postponing-1)
        self.sync += [
            If(self.start,
                count.eq(count.reset)
            ).Elif(executor.done,
                If(count != 0,
                    count.eq(count - 1)
                )
            )
        ]
        self.sync += executor.start.eq(self.start | (count != 0))
        self.sync += self.done.eq(executor.done & (count == 0))

# RefreshTimer -------------------------------------------------------------------------------------

class RefreshTimer(Module):
    """Refresh Timer

    Generate periodic pulses (tREFI period) to trigger DRAM refresh.
    """
    def __init__(self, trefi):
        self.wait  = Signal()
        self.done  = Signal()
        self.count = Signal(trefi.nbits)

        # # #

        done  = Signal()
        count = Signal(trefi.nbits)

        self.sync += [
            If(self.wait & ~self.done,
                count.eq(count - 1)
            ).Else(
                If(trefi != 0,
                    count.eq(trefi-1)
                )
            )
        ]
        self.comb += [
            done.eq(count == 0),
            self.done.eq(done),
            self.count.eq(count)
        ]

# RefreshPostponer -------------------------------------------------------------------------------

class RefreshPostponer(Module):
    """Refresh Postponer

    Postpone N Refresh requests and generate a request when N is reached.
    """
    def __init__(self, postponing=1):
        self.req_i = Signal()
        self.req_o = Signal()

        # # #

        count = Signal(bits_for(postponing), reset=postponing-1)
        self.sync += [
            self.req_o.eq(0),
            If(self.req_i,
                count.eq(count - 1),
                If(count == 0,
                    count.eq(count.reset),
                    self.req_o.eq(1)
                )
            )
        ]

# ZQCSExecutor ----------------------------------------------------------------------------------

class ZQCSExecutor(Module):
    """ZQ Short Calibration Executor

    Execute the ZQCS sequence to the DRAM:
    - Send a "Precharge All" command
    - Wait tRP
    - Send an "ZQ Short Calibration" command
    - Wait tZQCS
    """
    def __init__(self, cmd, trp, tzqcs):
        self.start = Signal()
        self.done  = Signal()

        # # #

        tlc = TimelineCounter(max(trp.nbits, tzqcs.nbits) + 1)
        self.submodules += tlc

        trp_max_val = 0
        tzqcs_max_val = 0
        if isinstance(trp, int):
            trp_max_val = trp
        else:
            trp_max_val = 2**trp.nbits

        if isinstance(tzqcs, int):
            tzqcs_max_val = tzqcs
        else:
            tzqcs_max_val = 2**tzqcs.nbits

        counter = Signal(max=trp_max_val+tzqcs_max_val)
        self.sync += counter.eq(trp+tzqcs)

        self.comb += [
            tlc.trigger.eq(self.start),
            tlc.target.eq(counter),
        ]

        self.sync += [
            # Note: Don't set cmd to 0 since already done in RefreshExecutor
            self.done.eq(0),
        ]

        self.sync += [
            If(tlc.trigger & (tlc.counter == 0),
                cmd.a.eq(  2**10),
                cmd.ba.eq( 0),
                cmd.cas.eq(0),
                cmd.ras.eq(1),
                cmd.we.eq( 1)
            ),
            If(tlc.counter == trp,
                cmd.a.eq(  0),
                cmd.ba.eq( 0),
                cmd.cas.eq(0),
                cmd.ras.eq(0),
                cmd.we.eq( 1),
            ),
            If(tlc.counter == trp + tzqcs,
                cmd.a.eq(  0),
                cmd.ba.eq( 0),
                cmd.cas.eq(0),
                cmd.ras.eq(0),
                cmd.we.eq( 0),
                self.done.eq(1),
            )
        ]

# Refresher ----------------------------------------------------------------------------------------

class Refresher(Module):
    """Refresher

    Manage DRAM refresh.

    The DRAM needs to be periodically refreshed with a tREFI period to avoid data corruption. During
    a refresh, the controller send a "Precharge All" command to close and precharge all rows and then
    send a "Auto Refresh" command.

    Before executing the refresh, the Refresher advertises the Controller that a refresh should occur,
    this allows the Controller to finish the current transaction and block next transactions. Once all
    transactions are done, the Refresher can execute the refresh Sequence and release the Controller.

    """
    def __init__(self, settings, clk_freq, timing_regs, zqcs_freq=1e0, postponing=1):
        assert postponing <= 8
        abits  = settings.geom.addressbits
        babits = settings.geom.bankbits + log2_int(settings.phy.nranks)
        self.cmd = cmd = stream.Endpoint(cmd_request_rw_layout(a=abits, ba=babits))

        # # #

        wants_refresh = Signal()
        wants_zqcs    = Signal()

        # Refresh Timer ----------------------------------------------------------------------------
        # if settings.timing.tREFI < 100: # FIXME: Reduce Margin.
        #     raise ValueError("Clk/tREFI is ratio too low , please increase Clk frequency or disable Refresh.")
        timer = RefreshTimer(timing_regs['tREFI'])
        self.submodules.timer = timer
        self.comb += timer.wait.eq(~timer.done)

        # Refresh Postponer ------------------------------------------------------------------------
        postponer = RefreshPostponer(postponing)
        self.submodules.postponer = postponer
        self.comb += postponer.req_i.eq(self.timer.done)
        self.comb += wants_refresh.eq(postponer.req_o)

        # Refresh Sequencer ------------------------------------------------------------------------
        sequencer = RefreshSequencer(cmd, timing_regs['tRP'], timing_regs['tRFC'], postponing)
        self.submodules.sequencer = sequencer

        if timing_regs.get('tZQCS', None) is not None:

            # ZQCS Timer ---------------------------------------------------------------------------
            zqcs_period = int(clk_freq / float(zqcs_freq))
            zqcs_timer_init = Signal(max=zqcs_period)
            self.comb += zqcs_timer_init.eq(zqcs_period)
            zqcs_timer = RefreshTimer(zqcs_timer_init)
            self.submodules.zqcs_timer = zqcs_timer
            self.comb += zqcs_timer.wait.eq(~zqcs_timer.done)

            # ZQCS Executor ------------------------------------------------------------------------
            zqcs_executor = ZQCSExecutor(cmd, timing_regs['tRP'], timing_regs['tZQCS'])
            self.submodules.zqs_executor = zqcs_executor

            # ZQCS request flag
            self.sync += If(~wants_zqcs & (timing_regs['tZQCS'] != 0),
                            wants_zqcs.eq(zqcs_timer.done)
                         ).Elif(wants_zqcs,
                            wants_zqcs.eq(~zqcs_executor.done)
                         )

        # Refresh FSM ------------------------------------------------------------------------------
        self.submodules.fsm = fsm = FSM()
        fsm.act("IDLE",
            If(settings.with_refresh,
                If(wants_refresh,
                    NextState("WAIT-BANK-MACHINES")
                )
            )
        )
        fsm.act("WAIT-BANK-MACHINES",
            cmd.valid.eq(1),
            If(cmd.ready,
                sequencer.start.eq(1),
                NextState("DO-REFRESH")
            )
        )
        if timing_regs.get('tZQCS', None) is None:
            fsm.act("DO-REFRESH",
                cmd.valid.eq(1),
                If(sequencer.done,
                    cmd.valid.eq(0),
                    cmd.last.eq(1),
                    NextState("IDLE")
                )
            )
        else:
            fsm.act("DO-REFRESH",
                cmd.valid.eq(1),
                If(sequencer.done,
                    If(wants_zqcs,
                        zqcs_executor.start.eq(1),
                        NextState("DO-ZQCS")
                    ).Else(
                        cmd.valid.eq(0),
                        cmd.last.eq(1),
                        NextState("IDLE")
                    )
                )
            )
            fsm.act("DO-ZQCS",
                cmd.valid.eq(1),
                If(zqcs_executor.done,
                    cmd.valid.eq(0),
                    cmd.last.eq(1),
                    NextState("IDLE")
                )
            )
