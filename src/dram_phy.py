# Copyright (c) 2023-2024 Antmicro <www.antmicro.com>
# SPDX-License-Identifier: Apache-2.0

from migen import *

from litedram.common import *
from litedram.phy.dfi import *

from litex.soc.interconnect.csr import *

from common import *
from dfi import *

# ==============================================================================

class PHYNone(Module, AutoCSR):
    """
    A PHY stub that exposes the DFI interface and provides configuration for
    the DRAM core
    """

    def __init__(self,
        memtype         = None,
        sys_clk_freq    = 100e6,
        nphases         = 4,
        ratio           = 4,
        addressbits     = 17,
        databits        = 32,
        bankbits        = 6,
        nranks          = 1,
        csr_cdc         = None,
        cl              = None,
        cwl             = None,
        cmd_latency     = 0,
        cmd_delay       = None,
        cwl_phy         = 0,
        read_latency    = None,
        write_latency   = None,
        rdphase         = None,
        wrphase         = None,
        t_phy_wrlat     = None,
    ):

        tck = 2/(2*ratio*sys_clk_freq)

        # Set address and bank bits for certain DDR types
        if memtype == "LPDDR4":
            addressbits = 17
            bankbits    = 6
        elif memtype == "DDR5":
            addressbits = 18
            bankbits    = 8
        elif memtype == "LDDR5":
            addressbits = 18
            bankbits    = 7

        self.memtype        = memtype
        self.nphases        = nphases
        self.addressbits    = addressbits
        self.databits       = databits
        self.bankbits       = bankbits
        self.nranks         = nranks

        assert memtype in ["DDR2", "DDR3", "DDR4", "DDR5", "LPDDR4", "LPDDR5"], memtype
        assert not (memtype == "DDR3" and nphases == 2)

        if memtype == "DDR4":
            addressbits += 3 # cas_n/ras_n/we_n multiplexed with address

        assert databits % 8 == 0, databits

        # Parameters -----------------------------------------------------------

        cl  = get_default_cl( memtype, tck) if cl  is None else cl
        cwl = get_default_cwl(memtype, tck) if cwl is None else cwl
        cl_sys_latency  = get_sys_latency(nphases, cl)
        cwl_sys_latency = get_sys_latency(nphases, cwl)
        if nphases > 1:
            if rdphase is None:
                rdphase = get_sys_phase(nphases, cl_sys_latency,   cl + cmd_latency)
            if wrphase is None:
                wrphase = get_sys_phase(nphases, cwl_sys_latency, cwl + cmd_latency)

        # CSRs -----------------------------------------------------------------
        self._rst = CSRStorage()

        if nphases > 1:
            self._rdphase = CSRStorage(log2_int(nphases), reset=rdphase)
            self._wrphase = CSRStorage(log2_int(nphases), reset=wrphase)

        def cdc(i):
            if csr_cdc is None:
                return i
            return csr_cdc(i)

        # PHY settings ---------------------------------------------------------

        write_latency = cwl_phy if write_latency is None else write_latency
        dfi_databits  = (databits * 2 * ratio) // nphases

        self.settings = PhySettings(
            phytype                   = self.__class__.__name__,
            memtype                   = memtype,
            databits                  = databits,
            strobes                   = None,
            dfi_databits              = dfi_databits,
            nranks                    = nranks,
            nphases                   = nphases,
            rdphase                   = 0 if nphases == 1 else self._rdphase.storage,
            wrphase                   = 0 if nphases == 1 else self._wrphase.storage,
            cl                        = cl,
            cwl                       = cwl,
            read_latency              = read_latency, # None, # read latency is controlled by PHY
            write_latency             = write_latency,
            t_phy_wrlat               = 0 if t_phy_wrlat is None else t_phy_wrlat, # write_latency,
            cmd_latency               = cmd_latency,
            cmd_delay                 = cmd_delay,
            write_leveling            = False,
            write_dq_dqs_training     = False,
            write_latency_calibration = False,
            read_leveling             = False,
            delays                    = 0,
            bitslips                  = 0,
            with_per_dq_idelay        = False,
            with_alert                = True,
            training_capable          = True,
        )

        # DFI Interface --------------------------------------------------------

        self.dfi = self.dfi_phy = dfi = Interface(addressbits, bankbits, nranks, dfi_databits, nphases)
        if memtype == "DDR4":
            dfi = Interface(addressbits, bankbits, nranks, dfi_databits, nphases)
            self.submodules += DDR4DFIMux(self.dfi, dfi)


def phynone_with_ratio(ratio, phy_cls=PHYNone, serdes_reset_cnt=0):
    """
    Generate PHY class that uses DFIRateConverter to increase MC:PHY frequency
    ratio
    """

    # Generate new class that wraps the original PHY
    wrapper_cls = DFIRateConverter.phy_wrapper(
        phy_cls          = phy_cls,
        ratio            = ratio,
        serdes_reset_cnt = serdes_reset_cnt,
        phy_attrs=["dfi_phy", "_rst"]
    )

    # Create a wrapper that will ensure that correct ddr_clk kwarg is passed to
    # the PHY
    def wrapper(*args, **kwargs):
        sys_clk_freq = kwargs.pop("sys_clk_freq", 150e6)
        return wrapper_cls(*args, sys_clk_freq=ratio * sys_clk_freq, **kwargs)

    return wrapper
