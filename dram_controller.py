#!/usr/bin/env python3
from migen import *

from litex.soc.interconnect.csr import CSRStorage, CSRStatus, CSRField, AutoCSR
from litedram.common import *
from litedram.phy import dfi
from litedram.core.refresher import Refresher
from litedram.core.bankmachine import BankMachine
from litedram.core.multiplexer import Multiplexer

from litedram.core.controller import ControllerSettings, \
                                     LiteDRAMControllerRegisterBank

# ==============================================================================

class DRAMController(Module):
    def __init__(self, phy_settings, geom_settings, timing_settings,
                 max_expected_values, clk_freq,
                 controller_settings=ControllerSettings()):

        if phy_settings.memtype == "SDR":
            burst_length = phy_settings.nphases
        else:
            burst_length = burst_lengths[phy_settings.memtype]

        address_align = log2_int(burst_length)

        # Settings -------------------------------------------------------------
        self.settings        = controller_settings
        self.settings.phy    = phy_settings
        self.settings.geom   = geom_settings
        self.settings.timing = timing_settings

        nranks = phy_settings.nranks
        nbanks = 2**geom_settings.bankbits

        # Registers ------------------------------------------------------------

        self.registers = registers = LiteDRAMControllerRegisterBank(
            phy_settings, timing_settings, max_expected_values,
            phy_settings.memtype)
        timing_regs = registers.get_register_signals()

        # LiteDRAM Interface (User) --------------------------------------------
        self.interface = interface = LiteDRAMInterface(
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
        self.submodules.refresher = self.settings.refresh_cls(self.settings,
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

