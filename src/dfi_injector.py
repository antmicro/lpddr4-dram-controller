# Copyright (c) 2015 Sebastien Bourdeauducq <sb@m-labs.hk>
# Copyright (c) 2016-2019 Florent Kermarrec <florent@enjoy-digital.fr>
# Copyright (c) 2023-2024 Antmicro <www.antmicro.com>
# SPDX-License-Identifier: BSD-2-Clause

from operator import or_, and_, add
from functools import reduce
from migen import *

from litex.soc.interconnect.csr import *
from litedram.common import TappedDelayLine
from litedram.phy.ddr5.commands import DFIPhaseAdapter
from litedram.dfii import DFIInjector, PhaseInjector, CmdInjector, DFISamplerDDR5

import dfi

# DFIInjector --------------------------------------------------------------------------------------

class DFIInjector(DFIInjector):
    def __init__(self, addressbits, bankbits, nranks, databits, nphases=1,
                 memtype=None, strobes=None, with_sub_channels=False):
        self.slave   = dfi.Interface(addressbits, bankbits, nranks, databits, nphases)
        self.master  = dfi.Interface(addressbits, bankbits, nranks, databits, nphases)
        csr1_dfi     = dfi.Interface(addressbits, bankbits, nranks, databits, nphases)
        self.intermediate   = dfi.Interface(addressbits, bankbits, nranks, databits, nphases)

        self.ext_dfi     = dfi.Interface(addressbits, bankbits, nranks, databits, nphases)
        self.ext_dfi_sel = Signal()

        prefixes = [""] if not with_sub_channels else ["A_", "B_"]

        if memtype == "DDR5":
            csr2_dfi     = dfi.Interface(14, 1, nranks, databits, nphases, with_sub_channels)
            ddr5_dfi     = dfi.Interface(14, 1, nranks, databits, nphases)

            masked_writes  = False
            if databits//2//strobes in [8, 16]:
                masked_writes = True
            adapters = [DFIPhaseAdapter(phase, masked_writes) for phase in self.intermediate.phases]
            self.submodules += adapters

        if memtype == "DDR5":
            self.master = dfi.Interface(14, 1, nranks, databits, nphases, with_sub_channels)

        extra_fields = []
        if memtype == "DDR5":
            extra_fields.append(
                CSRField("mode_2n", size=1, values=[
                    ("``0b0``", "In 1N mode"),
                    ("``0b1``", "In 2N mode (Default)"),
                ], reset=0b1)
            )
            for prefix in prefixes:
                extra_fields.append(
                    CSRField(prefix+"control", size=1, values=[
                        ("``0b1``", prefix+"Cmd Injector"),
                    ], reset=0b0)
                )

        self._control = CSRStorage(fields=[
            CSRField("sel",     size=1, values=[
                ("``0b0``", "Software (CPU) control."),
                ("``0b1``", "Hardware control (default)."),
            ], reset=0b1), # Defaults to HW control.
            CSRField("cke",     size=1, description="DFI clock enable bus"),
            CSRField("odt",     size=1, description="DFI on-die termination bus"),
            CSRField("reset_n", size=1, description="DFI clock reset bus"),
        ] + extra_fields,
        description="Control DFI signals common to all phases")

        if memtype != "DDR5":
            for n, phase in enumerate(csr1_dfi.phases):
                setattr(self.submodules, "pi" + str(n), PhaseInjector(phase))
            # # #

            self.comb += [
                Case(self._control.fields.sel, {
                    # Software Control (through CSRs).
                    # --------------------------------
                    0: csr1_dfi.connect(self.intermediate),
                    # Hardware Control.
                    # -----------------
                    1: # Through External DFI.
                        If(self.ext_dfi_sel,
                            self.ext_dfi.connect(self.intermediate)
                        # Through LiteDRAM controller.
                        ).Else(
                            self.slave.connect(self.intermediate)
                        ),
                })
            ]
            for i in range(nranks):
                self.comb += [phase.cke[i].eq(self._control.fields.cke) for phase in csr1_dfi.phases]
                self.comb += [phase.odt[i].eq(self._control.fields.odt) for phase in csr1_dfi.phases if hasattr(phase, "odt")]
            self.comb += [phase.reset_n.eq(self._control.fields.reset_n) for phase in csr1_dfi.phases if hasattr(phase, "reset_n")]
            self.comb += [self.intermediate.connect(self.master)]

            # Make DFI control signals bypass the mux and be always controlled
            # by software.
            self.comb += [
                self.intermediate.ctl.init_start.eq(self.slave.ctl.init_start),
                self.slave.ctl.init_complete.eq(self.intermediate.ctl.init_complete),
            ]

        else: # memtype == "DDR5"
            self.comb += [
                # Hardware Control.
                # -----------------
                # Through External DFI
                If(self.ext_dfi_sel,
                    self.ext_dfi.connect(self.intermediate)
                # Through LiteDRAM controller.
                ).Else(
                    self.slave.connect(self.intermediate)
                ),
            ]

            # TODO: Handle dfi.ctl signals

            for prefix in prefixes:
                setattr(self.submodules, prefix.lower()+"cmdinjector", CmdInjector(csr2_dfi.get_subchannel(prefix), masked_writes))

            # DRAM controller is not DFI compliant. It creats only single wrdata_en/rddata_en strobe,
            # but DFI requires wrdata_en/rddata_en per each data slice,
            # so in BL16 it should create 8 and in BL8 , it should do 4

            # We need to store at least 16 wrdata_en and rddata en.
            # Code assumes that wrdata_en/rddata_en are transmitted
            # in the same DFI cycle and in the phase as WRITE/READ commands
            data_en_depth = max(16//nphases + 1, 2)

            data_en_delays = [None] * data_en_depth

            for i in range(data_en_depth):
                assert data_en_delays[i] == None
                data_en_delays[i] = []
                for _ in range(nphases):
                    _input  = Signal(2)
                    _output = Signal(2)
                    self.comb += _output.eq(_input)
                    if i:
                        tap_line = TappedDelayLine(signal=_input, ntaps=i)
                        self.submodules += tap_line
                        self.comb += _output.eq(tap_line.output)
                    assert i <= data_en_depth, (i, data_en_depth)
                    data_en_delays[i].append((_input, _output))

            for i, adapter in enumerate(adapters):
                _bl8_acts = []
                _bl16_acts = []
                origin_phase = self.intermediate.phases[i]
                for j in range(4):
                    phase_num = (i+j)  % nphases
                    delay     = (i+j) // nphases
                    _input, _ = data_en_delays[delay][phase_num]
                    _bl8_acts.append(_input.eq(_input | Cat(origin_phase.wrdata_en, origin_phase.rddata_en)))

                for j in range(8):
                    phase_num = (i+j)  % nphases
                    delay     = (i+j) // nphases
                    _input, _ = data_en_delays[delay][phase_num]
                    _bl16_acts.append(_input.eq(_input | Cat(origin_phase.wrdata_en, origin_phase.rddata_en)))

                self.comb += [
                    If(adapter.bl16,
                        *_bl16_acts,
                    ).Else(
                        *_bl8_acts,
                    )
                ]

            for ddr5_phase, inter_phase in zip(ddr5_dfi.phases, self.intermediate.phases):
                self.comb += [
                    ddr5_phase.wrdata.eq(inter_phase.wrdata),
                    ddr5_phase.wrdata_mask.eq(inter_phase.wrdata_mask),
                    inter_phase.rddata.eq(ddr5_phase.rddata),
                    inter_phase.rddata_valid.eq(ddr5_phase.rddata_valid),
                ]
            for i in range(data_en_depth):
                for (_, _output), phase in zip(data_en_delays[i], ddr5_dfi.phases):
                    self.comb += [
                        phase.wrdata_en.eq(phase.wrdata_en | _output[0]),
                        phase.rddata_en.eq(phase.rddata_en | _output[1]),
                    ]

            # DDR5 has commands that take either 1 or 2 CA cycles.
            # It also has the 2N mode, that is enabled by default.
            # It stretches single CA packet to 2 clock cycles. It is necessary when CA and
            # CS aren't trained. Adapter modules from phy/ddr5/commands.py solve
            # translation from the old DDR4 commands to DDR5 type. If an adapter
            # creates 2 beat command, and command was in phase 3 and DFI has 4
            # phases, we have to carry next part of command to the next clock cycle.
            # This issue is even more profound when 2N mode is used. All commands
            # will take 2 or 4 cycles to be correctly transmitted.

            depth = max(4//nphases + 1, 2)

            delays = [None] * depth

            for i in range(depth):
                assert delays[i] == None
                delays[i] = []
                for _ in range(nphases):
                    _input = Signal(14+nranks)
                    tap_line = TappedDelayLine(signal=_input, ntaps=i+1)
                    self.submodules += tap_line
                    delays[i].append((_input, tap_line))

            for i, adapter in enumerate(adapters):
                # 0 CA0 always
                # 1 CA0 if 2N mode or CA1 if 1N mode
                # 2 CA1 if 2N mode
                # 3 CA1 if 2N mode

                phase = ddr5_dfi.phases[i]
                self.comb += [
                    If(adapter.valid,
                        phase.address.eq(phase.address | adapter.ca[0]),
                        phase.cs_n.eq(phase.cs_n & adapter.cs_n[0]),
                    ),
                    phase.reset_n.eq(self._control.fields.reset_n),
                    phase.mode_2n.eq(self._control.fields.mode_2n),
                ]

                phase_num = (i+1) % nphases
                delay     = (i+1) // nphases
                if delay:
                    _input, _ = delays[delay-1][phase_num]
                    self.comb += If(self._control.fields.mode_2n & adapter.valid,
                        _input.eq(Cat(adapter.cs_n[1], adapter.ca[0])),
                    ).Elif(adapter.valid,
                        _input.eq(Cat(adapter.cs_n[1], adapter.ca[1])),
                    )
                else:
                    phase = ddr5_dfi.phases[phase_num]
                    self.comb += If(self._control.fields.mode_2n & adapter.valid,
                        phase.address.eq(phase.address | adapter.ca[0]),
                        phase.cs_n.eq(phase.cs_n & adapter.cs_n[1]),
                    ).Elif(adapter.valid,
                        phase.address.eq(phase.address | adapter.ca[1]),
                        phase.cs_n.eq(phase.cs_n & adapter.cs_n[1]),
                    )

                for j in [2,3]:
                    phase_num = (j+i) % nphases
                    delay     = (i+j) // nphases # Number of cycles to delay
                    if delay:
                        _input, _ = delays[delay-1][phase_num]
                        self.comb += If(self._control.fields.mode_2n & adapter.valid,
                            _input.eq(Cat(adapter.cs_n[j//2], adapter.ca[j//2])),
                        )
                    else:
                        phase = ddr5_dfi.phases[phase_num]
                        self.comb += If(self._control.fields.mode_2n & adapter.valid,
                            phase.address.eq(phase.address | adapter.ca[j//2]),
                            phase.cs_n.eq(phase.cs_n & adapter.cs_n[j//2]),
                        )

            for i in range(depth):
                for (_, delay_out), phase in zip(delays[i], ddr5_dfi.phases):
                    self.comb += phase.cs_n.eq(   phase.cs_n    | delay_out.output[0:nranks])
                    self.comb += phase.address.eq(phase.address | delay_out.output[nranks:-1])

            if with_sub_channels:
                ddr5_dfi.create_sub_channels()
                ddr5_dfi.remove_common_signals()

            for prefix in prefixes:
                setattr(self.submodules, prefix.lower()+"dfisampler",  DFISamplerDDR5(self.master.phases, prefix))

            self.comb += [
                Case(self._control.fields.sel, {
                    # Software Control (through CSRs).
                    # --------------------------------
                    0: [
                        Case(getattr(self._control.fields, prefix+"control"), {
                            1: [cp.connect(mp) for cp, mp in zip(csr2_dfi.get_subchannel(prefix), self.master.get_subchannel(prefix))],
                            0: [mp.cs_n.eq(Replicate(1, nranks)) for mp in self.master.get_subchannel(prefix)], # Use DES on unselected channels
                        }) for prefix in prefixes
                    ] + [
                        phase.reset_n.eq(self._control.fields.reset_n) for phase in self.master.phases if hasattr(phase, "reset_n")
                    ] + [
                        phase.mode_2n.eq(self._control.fields.mode_2n) for phase in self.master.phases if hasattr(phase, "mode_2n")
                    ],
                    # Hardware Control.
                    # -----------------
                    1: ddr5_dfi.connect(self.master),
                })
            ]
