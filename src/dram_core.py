# Copyright (c) 2016-2019 Florent Kermarrec <florent@enjoy-digital.fr>
# Copyright (c) 2023 Antmicro <www.antmicro.com>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.soc.interconnect.csr import CSRStorage, CSRStatus, CSRField, AutoCSR
from litedram.core.bankmachine import BankMachine

from common import *
from multiplexer import Multiplexer
from dfi_injector import DFIInjector
from dram_crossbar import DRAMCrossbar
from refresher import Refresher

from litedram.core.controller import ControllerSettings, \
    LiteDRAMControllerRegisterBank, REGISTER_NAMES

import dfi

# ==============================================================================

class DRAMControllerRegisterBank(LiteDRAMControllerRegisterBank):
    def __init__(self, phy_settings, initial_timings, max_expected_values, memtype):
        for reg in REGISTER_NAMES:
            if reg == "tZQCS" and memtype in ["LPDDR4", "LPDDR5", "DDR5"]:
                continue # ZQCS refresher does not work with LPDDR4, LPDDR5 and DDR5
            try:
                width = getattr(max_expected_values, reg)
            except AttributeError:
                width = None
            width = (width.bit_length() + 1) if width is not None else 1
            reset_val = None
            if initial_timings is not None:
                try:
                    reset_val = getattr(initial_timings, reg)
                except AttributeError:
                    reset_val = None
            csr = CSRStorage(width, name=reg, reset=reset_val if reset_val is not None else 0)
            assert reset_val is None or reset_val < 2**width, (reg, reset_val, 2**width)
            setattr(self, reg, csr)

        if phy_settings.training_capable:
            self.phy_ctl = CSRStorage(
                fields = [
                    CSRField("init_req",  size=1, offset=0, reset=0, pulse=True,
                                          description="Initiates PHY training"),
                ],
            )
            self.phy_sts = CSRStatus(
                fields = [
                    CSRField("init_done", size=1, offset=0, reset=0,
                                          description="Set to one upon PHY training completion"),
                ],
            )

# ==============================================================================

class DRAMController(Module):
    def __init__(self, phy_settings, geom_settings, timing_settings,
                 max_expected_values, clk_freq,
                 controller_settings=ControllerSettings()):

        if phy_settings.memtype == "SDR":
            burst_length = phy_settings.nphases
        else:
            burst_length = burst_lengths[phy_settings.memtype]

        # FIXME: Unless changed burst_lengths["DDR3"] evaluates to 8 which is
        # fixed (not computed from the controller config). This may lead to
        # address skipping eg. when the DFI bus word is shorter than 8.

        address_align = log2_int(burst_length)

        # Settings -------------------------------------------------------------
        self.settings        = controller_settings
        self.settings.phy    = phy_settings
        self.settings.geom   = geom_settings
        self.settings.timing = timing_settings

        nranks = phy_settings.nranks
        nbanks = 2**geom_settings.bankbits

        # Registers ------------------------------------------------------------

        self.registers = registers = DRAMControllerRegisterBank(
            phy_settings, timing_settings, max_expected_values,
            phy_settings.memtype)
        timing_regs = registers.get_register_signals()

        # LiteDRAM Interface (User) --------------------------------------------
        self.interface = interface = DRAMInterface(
            address_align, self.settings)

        # DFI Interface (Memory) -----------------------------------------------
        self.dfi = dfi.Interface(
            addressbits = geom_settings.addressbits,
            bankbits    = geom_settings.bankbits,
            nranks      = phy_settings.nranks,
            databits    = phy_settings.dfi_databits,
            nphases     = phy_settings.nphases)

        # # #

        # Refresher ------------------------------------------------------------
        self.submodules.refresher = Refresher(self.settings,
            clk_freq    = clk_freq,
            timing_regs = timing_regs,
            zqcs_freq   = self.settings.refresh_zqcs_freq,
            postponing  = self.settings.refresh_postponing)

        # Bank Machines --------------------------------------------------------

        # tWTP (write-to-precharge) calculation -------------------------------
        write_latency = math.ceil(self.settings.phy.cwl / self.settings.phy.nphases)
        max_precharge_time = write_latency + max_expected_values.tWR + max_expected_values.tCCD # AL=0
        precharge_time_sig = Signal(max_precharge_time.bit_length())
        precharge_time = write_latency + timing_regs['tWR'] + timing_regs['tCCD'] # AL=0
        # Value changes only on registers update, use sync to reduce critical path length
        self.sync += precharge_time_sig.eq(precharge_time)

        bank_machines = []
        for n in range(nranks*nbanks):
            bank_machine = BankMachine(n,
                address_width       = interface.address_width,
                address_align       = address_align,
                nranks              = nranks,
                settings            = self.settings,
                timing_regs         = timing_regs,
                precharge_time_sig  = precharge_time_sig)
            bank_machines.append(bank_machine)
            self.submodules += bank_machine
            self.comb += getattr(interface, "bank"+str(n)).connect(bank_machine.req)

        # Multiplexer ----------------------------------------------------------
        self.submodules.multiplexer = Multiplexer(
            settings      = self.settings,
            bank_machines = bank_machines,
            refresher     = self.refresher,
            dfi           = self.dfi,
            interface     = interface,
            timing_regs   = timing_regs)

        # ----------------------------------------------------------------------
        if phy_settings.training_capable:

            init_start = Signal()
            init_complete = Signal()

            self.sync += [
                If(self.registers.phy_ctl.re & self.registers.phy_ctl.fields.init_req,
                    init_start.eq(self.registers.phy_ctl.fields.init_req),
                    self.registers.phy_sts.fields.init_done.eq(0)
                ),
                If(init_complete,
                    init_start.eq(0),
                    self.registers.phy_sts.fields.init_done.eq(1)
                )
            ]

            self.comb += [
                self.dfi.ctl.init_start.eq(init_start),
                init_complete.eq(self.dfi.ctl.init_complete),
            ]

    def get_csrs(self):
        return self.multiplexer.get_csrs() + self.registers.get_csrs()

# ==============================================================================

class DRAMCore(Module, AutoCSR):
    def __init__(self, phy, module, clk_freq, **kwargs):
        self.submodules.dfii = DFIInjector(
            addressbits = max(module.geom_settings.addressbits, getattr(phy, "addressbits", 0)),
            bankbits    = max(module.geom_settings.bankbits, getattr(phy, "bankbits", 0)),
            nranks      = phy.settings.nranks,
            databits    = phy.settings.dfi_databits,
            nphases     = phy.settings.nphases,
            memtype     = phy.settings.memtype,
            strobes     = phy.settings.strobes,
            with_sub_channels= phy.settings.with_sub_channels)
        self.comb += self.dfii.master.connect(phy.dfi)

        self.submodules.controller = controller = DRAMController(
            phy_settings        = phy.settings,
            geom_settings       = module.geom_settings,
            timing_settings     = module.timing_settings,
            max_expected_values = module.maximal_timing_values,
            clk_freq            = clk_freq,
            **kwargs)
        self.comb += controller.dfi.connect(self.dfii.slave)

        self.submodules.crossbar = DRAMCrossbar(controller.interface)
