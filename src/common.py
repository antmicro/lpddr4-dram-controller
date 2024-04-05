# Copyright (c) 2016-2019 Florent Kermarrec <florent@enjoy-digital.fr>
# Copyright (c) 2018 John Sully <john@csquare.ca>
# Copyright (c) 2018 bunnie <bunnie@kosagi.com>
# Copyright (c) 2020-2024 Antmicro <www.antmicro.com>
# SPDX-License-Identifier: BSD-2-Clause

import math
from functools import reduce
from operator import add
from collections import OrderedDict
from typing import Union, Optional

from migen import *

from litex.soc.interconnect import stream

from litedram.common import *

# Settings -----------------------------------------------------------------------------------------

class PhySettings(Settings):
    def __init__(self,
            phytype: str,
            memtype: str,  # SDR, DDR, DDR2, ...
            databits: int,  # number of DQ lines
            dfi_databits: int,  # per-phase DFI data width
            nphases: int,  # number of DFI phases
            rdphase: Union[int, Signal],  # phase on which READ command will be issued by MC
            wrphase: Union[int, Signal],  # phase on which WRITE command will be issued by MC
            cl: int,  # latency (DRAM clk) from READ command to first data
            read_latency: int,  # latency (MC clk) from DFI.rddata_en to DFI.rddata_valid
            write_latency: int,  # latency (MC clk) from DFI.wrdata_en to DFI.wrdata
            strobes: Optional[int] = None,  # number of DQS lines
            nranks: int = 1,  # number of DRAM ranks
            cwl: Optional[int] = None,  # latency (DRAM clk) from WRITE command to first data
            cmd_latency: Optional[int] = None,  # additional command latency (MC clk)
            cmd_delay: Optional[int] = None,  # used to force cmd delay during initialization in BIOS
            bitslips: int = 0,  # number of write/read bitslip taps
            delays: int = 0,  # number of write/read delay taps
            with_alert: bool = False, # phy has CSRs for reading and reseting alert condition
            # Minimal delay between data being send to phy and them showing on DQ lines
            # If CLW is delay from write command to data on DQ, SW should add CLW-min_write_latency delay cycles
            min_write_latency: int = 0,
            # Minimal delay between read command being send and DQ lines being captured
            # If CL is delay from read command to data on DQ, SW should add CL-min_read_latency delay cycles
            min_read_latency: int = 0,
            # PHY training capabilities
            write_leveling: bool = False,
            write_dq_dqs_training: bool = False,
            write_latency_calibration: bool = False,
            read_leveling: bool = False,
            with_sub_channels: bool = False,
            # DDR5 specific
            address_lines: int = 13,
            with_per_dq_idelay: bool = False,
            with_address_odelay: bool = False, # Concrete PHY has ODELAYs on all address lines
            with_clock_odelay: bool = False, # Concrete PHY has ODELAYs on clk lines
            with_odelay: bool = False, # Concrete PHY has ODELAYs on all lines: CLK, CS/CA, DQ/DQS
            with_idelay: bool = False, # Concrete PHY has IDELAYs on DQ/DQS lines
            direct_control: bool = False,
            # DFI timings
            t_ctrl_delay: int = 0,  # Time from the DFI command to its appearance on DRAM bus
            t_parin_lat: int = 0,   # Time from the DFI command to its parity
            t_cmd_lat: int = 0,     # Time from the CS to DFI command
            t_phy_wrdata: int  = 0, # Time from the wrdata_en to wrdata an wrdata_mask
            t_phy_wrlat: int = 0,   # Time from the DFI Write command to wrdata_en
            t_phy_wrcsgap: int = 0, # Additional delay when changing physical ranks (wrdata_cs/cs)
            t_phy_wrcslat: int = 0, # Time from the DFI Write command to wrdata_cs
            t_phy_rdlat: int = 0,   # Max delay from the DFI rddata_en to rddata_valid
            t_rddata_en: int = 0,   # Time from the DFI Read command to rddata_en
            t_phy_rdcsgap: int  = 0,# Additional delay when changing physical ranks (rddata_cs/cs)
            t_phy_rdcslat: int = 0, # Time from the DFI Write command to rddata_cs
            # Training in PHY. DFI interface v5.0 assumes that the whole training is done in PHY
            training_capable: bool = False,
        ):
        if strobes is None:
            strobes = databits // 8
        self.set_attributes(locals())
        self.cwl = cl if cwl is None else cwl
        self.is_rdimm = False

    # Optional DDR3/DDR4 electrical settings:
    # rtt_nom: Non-Writes on-die termination impedance
    # rtt_wr: Writes on-die termination impedance
    # ron: Output driver impedance
    # tdqs: Termination Data Strobe enable.
    def add_electrical_settings(self, rtt_nom=None, rtt_wr=None, ron=None, tdqs=None):
        assert self.memtype in ["DDR3", "DDR4"]
        if rtt_nom is not None:
            self.rtt = rtt_nom
        if rtt_wr is not None:
            self.rtt_wr = rtt_wr
        if ron is not None:
            self.ron = ron
        if tdqs is not None:
            self.tdqs = tdqs

    # Optional RDIMM configuration
    def set_rdimm(self, tck, rcd_pll_bypass, rcd_ca_cs_drive, rcd_odt_cke_drive, rcd_clk_drive):
        assert self.memtype == "DDR4"
        self.is_rdimm = True
        self.set_attributes(locals())

# Layouts/Interface --------------------------------------------------------------------------------

def data_layout(data_width):
    return [
        ("wdata",       data_width, DIR_M_TO_S),
        ("wdata_we", data_width//8, DIR_M_TO_S),
        ("rdata",       data_width, DIR_S_TO_M),
        ("rdata_valid",          1, DIR_S_TO_M)
    ]

class DRAMInterface(LiteDRAMInterface):
    def __init__(self, address_align, settings):
        rankbits = log2_int(settings.phy.nranks)
        self.address_align = address_align
        self.address_width = settings.geom.rowbits + settings.geom.colbits + rankbits - address_align
        self.data_width    = settings.phy.dfi_databits*settings.phy.nphases
        self.nbanks   = settings.phy.nranks*(2**settings.geom.bankbits)
        self.nranks   = settings.phy.nranks
        self.settings = settings

        layout = [("bank"+str(i), cmd_layout(self.address_width)) for i in range(self.nbanks)]
        layout += data_layout(self.data_width)
        Record.__init__(self, layout)
