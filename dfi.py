# Copyright (c) 2015 Sebastien Bourdeauducq <sb@m-labs.hk>
# Copyright (c) 2021-2023 Antmicro <www.antmicro.com>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *
from migen.fhdl.structure import _Slice
from migen.genlib.record import *
from migen.genlib.cdc import PulseSynchronizer

from litedram.phy.utils import Serializer, Deserializer
from litedram.phy.dfi import *


class Interface(litedram.phy.dfi.Interface):
    def __init__(self, addressbits, bankbits, nranks, databits, nphases=1, with_sub_channels=False):
        self.with_sub_channels = with_sub_channels
        self.databits = databits

        control = [
            ("init_start",      1,  DIR_M_TO_S),
            ("init_complete",   1,  DIR_S_TO_M),
        ]

        layout  = [("p"+str(i), phase_description(addressbits, bankbits, nranks, databits, with_sub_channels)) for i in range(nphases)]
        layout += [("ctl", [spec for spec in control])]

        Record.__init__(self, layout)

        self.phases  = [getattr(self, "p"+str(i)) for i in range(nphases)]
        self.control = [getattr(self.ctl, spec[0]) for spec in control]

        prefixes = [""] if not with_sub_channels else ["A_", "B_"]
        if not with_sub_channels:
            for p in self.phases:
                setattr(p, "", p)
        for p in self.phases:
            for prefix in prefixes:
                getattr(p, prefix).cas_n.reset = 1
                getattr(p, prefix).cs_n.reset = (2**nranks-1)
                getattr(p, prefix).ras_n.reset = 1
                getattr(p, prefix).we_n.reset = 1
                getattr(p, prefix).act_n.reset = 1
            p.mode_2n.reset = 0

    # Returns pairs (DFI-mandated signal name, Migen signal object)
    def get_standard_names(self, m2s=True, s2m=True):
        r = []
        add_suffix = len(self.phases) > 1
        for n, phase in enumerate(self.phases):
            for field, size, direction in phase.layout:
                if (m2s and direction == DIR_M_TO_S) or (s2m and direction == DIR_S_TO_M):
                    if add_suffix:
                        if direction == DIR_M_TO_S:
                            suffix = "_p" + str(n)
                        else:
                            suffix = "_w" + str(n)
                    else:
                        suffix = ""
                    r.append(("dfi_" + field + suffix, getattr(phase, field)))
        for field, size, direction in self.ctl.layout:
            if (m2s and direction == DIR_M_TO_S) or (s2m and direction == DIR_S_TO_M):
                r.append(("dfi_" + field, getattr(self.ctl, field)))
        return r
