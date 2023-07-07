#!/usr/bin/env python3
#
# Copyright (c) 2018-2021 Florent Kermarrec <florent@enjoy-digital.fr>
# Copyright (c) 2020 Stefan Schrijvers <ximin@ximinity.net>
# Copyright (c) 2023 Antmicro <www.antmicro.com>
# SPDX-License-Identifier: BSD-2-Clause

import os
import yaml
import argparse
import inspect

from migen import *

from litex.soc.interconnect.csr import AutoCSR, CSRStorage
from litex.soc.interconnect import wishbone
from litex.soc.integration.soc import LiteXSoC

from litex.build.generic_toolchain import GenericToolchain
from litex.build.generic_platform import GenericPlatform, Pins, Subsignal
from litex.soc.integration.builder import Builder

from litedram.frontend.wishbone import *

from litedram import modules as litedram_modules
from litedram.phy import PHYNone
from litedram.core.controller import ControllerSettings

from dram_core import DRAMCore

# ------------------------------------------------------------------------------

class NoToolchain(GenericToolchain):
    """
    Generic toolchain stub
    """

    def __init__(self, *args, **kwargs):
        GenericToolchain.__init__(self, *args, **kwargs)

    def build_io_constraints(self):
        pass

    def build_script(self):
        pass


class NoPlatform(GenericPlatform):
    """
    Generic platform stub
    """

    def __init__(self, *args, **kwargs):
        GenericPlatform.__init__(self, *args, **kwargs)
        self.toolchain = NoToolchain()

    def build(self, *args, **kwargs):
        return self.toolchain.build(self, *args, **kwargs)


# IOs/Interfaces -----------------------------------------------------------------------------------

def get_common_ios():
    return [
        # Clk/Rst.
        ("clk", 0, Pins(1)),
        ("rst", 0, Pins(1)),

        # Init status.
        ("init_done",  0, Pins(1)),
        ("init_error", 0, Pins(1)),
    ]

def get_dram_ios(core_config):
    assert core_config["memtype"] in ["SDR", "DDR2", "DDR3", "DDR4"]

    # SDR.
    if core_config["memtype"] in ["SDR"]:
        return [
            ("sdram", 0,
                Subsignal("a",       Pins(log2_int(core_config["sdram_module"].nrows))),
                Subsignal("ba",      Pins(log2_int(core_config["sdram_module"].nbanks))),
                Subsignal("ras_n",   Pins(1)),
                Subsignal("cas_n",   Pins(1)),
                Subsignal("we_n",    Pins(1)),
                Subsignal("cs_n",    Pins(1)),
                Subsignal("dm",      Pins(core_config["sdram_module_nb"])),
                Subsignal("dq",      Pins(8*core_config["sdram_module_nb"])),
                Subsignal("cke",     Pins(1))
            ),
        ]

    # DDR2 / DDR3.
    if core_config["memtype"] in ["DDR2", "DDR3"]:
        return [
            ("ddram", 0,
                Subsignal("a",       Pins(log2_int(core_config["sdram_module"].nrows))),
                Subsignal("ba",      Pins(log2_int(core_config["sdram_module"].nbanks))),
                Subsignal("ras_n",   Pins(1)),
                Subsignal("cas_n",   Pins(1)),
                Subsignal("we_n",    Pins(1)),
                Subsignal("cs_n",    Pins(core_config["sdram_rank_nb"])),
                Subsignal("dm",      Pins(core_config["sdram_module_nb"])),
                Subsignal("dq",      Pins(8*core_config["sdram_module_nb"])),
                Subsignal("dqs_p",   Pins(core_config["sdram_module_nb"])),
                Subsignal("dqs_n",   Pins(core_config["sdram_module_nb"])),
                Subsignal("clk_p",   Pins(core_config["sdram_rank_nb"])),
                Subsignal("clk_n",   Pins(core_config["sdram_rank_nb"])),
                Subsignal("cke",     Pins(core_config["sdram_rank_nb"])),
                Subsignal("odt",     Pins(core_config["sdram_rank_nb"])),
                Subsignal("reset_n", Pins(1))
            ),
        ]
    # DDR4.
    if core_config["memtype"] == "DDR4":
        # On DDR4, A14. A15 and A16 are shared with we_n/cas_n/ras_n
        a_width = min(log2_int(core_config["sdram_module"].nrows), 14)
        return [
            ("ddram", 0,
                Subsignal("a",       Pins(a_width)),
                Subsignal("ba",      Pins(log2_int(core_config["sdram_module"].ngroupbanks))),
                Subsignal("bg",      Pins(log2_int(core_config["sdram_module"].ngroups))),
                Subsignal("ras_n",   Pins(1)),
                Subsignal("cas_n",   Pins(1)),
                Subsignal("we_n",    Pins(1)),
                Subsignal("cs_n",    Pins(core_config["sdram_rank_nb"])),
                Subsignal("act_n",   Pins(1)),
                Subsignal("dm",      Pins(core_config["sdram_module_nb"])),
                Subsignal("dq",      Pins(8*core_config["sdram_module_nb"])),
                Subsignal("dqs_p",   Pins(core_config["sdram_module_nb"])),
                Subsignal("dqs_n",   Pins(core_config["sdram_module_nb"])),
                Subsignal("clk_p",   Pins(core_config["sdram_rank_nb"])),
                Subsignal("clk_n",   Pins(core_config["sdram_rank_nb"])),
                Subsignal("cke",     Pins(core_config["sdram_rank_nb"])),
                Subsignal("odt",     Pins(core_config["sdram_rank_nb"])),
                Subsignal("reset_n", Pins(1))
            ),
        ]

def get_native_user_port_ios(_id, aw, dw):
    return [
        ("user_port_{}".format(_id), 0,
            # cmd
            Subsignal("cmd_valid", Pins(1)),
            Subsignal("cmd_ready", Pins(1)),
            Subsignal("cmd_we",    Pins(1)),
            Subsignal("cmd_addr",  Pins(aw)),

            # wdata
            Subsignal("wdata_valid", Pins(1)),
            Subsignal("wdata_ready", Pins(1)),
            Subsignal("wdata_we",    Pins(dw//8)),
            Subsignal("wdata_data",  Pins(dw)),

            # rdata
            Subsignal("rdata_valid", Pins(1)),
            Subsignal("rdata_ready", Pins(1)),
            Subsignal("rdata_data",  Pins(dw))
        ),
    ]

def get_wishbone_user_port_ios(_id, aw, dw):
    return [
        ("user_port_{}".format(_id), 0,
            Subsignal("adr",   Pins(aw)),
            Subsignal("dat_w", Pins(dw)),
            Subsignal("dat_r", Pins(dw)),
            Subsignal("sel",   Pins(dw//8)),
            Subsignal("cyc",   Pins(1)),
            Subsignal("stb",   Pins(1)),
            Subsignal("ack",   Pins(1)),
            Subsignal("we",    Pins(1)),
            Subsignal("err",   Pins(1)),
        ),
    ]

def get_axi_user_port_ios(_id, aw, dw, iw):
    return [
        ("user_port_{}".format(_id), 0,
            # aw
            Subsignal("awvalid", Pins(1)),
            Subsignal("awready", Pins(1)),
            Subsignal("awaddr",  Pins(aw)),
            Subsignal("awburst", Pins(2)),
            Subsignal("awlen",   Pins(8)),
            Subsignal("awsize",  Pins(4)),
            Subsignal("awid",    Pins(iw)),

            # w
            Subsignal("wvalid", Pins(1)),
            Subsignal("wready", Pins(1)),
            Subsignal("wlast",  Pins(1)),
            Subsignal("wstrb",  Pins(dw//8)),
            Subsignal("wdata",  Pins(dw)),

            # b
            Subsignal("bvalid", Pins(1)),
            Subsignal("bready", Pins(1)),
            Subsignal("bresp",  Pins(2)),
            Subsignal("bid",    Pins(iw)),

            # ar
            Subsignal("arvalid", Pins(1)),
            Subsignal("arready", Pins(1)),
            Subsignal("araddr",  Pins(aw)),
            Subsignal("arburst", Pins(2)),
            Subsignal("arlen",   Pins(8)),
            Subsignal("arsize",  Pins(4)),
            Subsignal("arid",    Pins(iw)),

            # r
            Subsignal("rvalid", Pins(1)),
            Subsignal("rready", Pins(1)),
            Subsignal("rlast",  Pins(1)),
            Subsignal("rresp",  Pins(2)),
            Subsignal("rdata",  Pins(dw)),
            Subsignal("rid",    Pins(iw))
        ),
    ]

def get_fifo_user_port_ios(_id, dw):
    return [
        ("user_fifo_{}".format(_id), 0,
            # in
            Subsignal("in_valid", Pins(1)),
            Subsignal("in_ready", Pins(1)),
            Subsignal("in_data",  Pins(dw)),

            # out
            Subsignal("out_valid", Pins(1)),
            Subsignal("out_ready", Pins(1)),
            Subsignal("out_data",  Pins(dw)),
        ),
    ]

# DRAMCoreControl ----------------------------------------------------------------------------------

class DRAMCoreControl(Module, AutoCSR):
    def __init__(self):
        self.init_done  = CSRStorage()
        self.init_error = CSRStorage()

# DRAMCoreSoC -------------------------------------------------------------------------------------

class DRAMCoreSoC(LiteXSoC):

    def __init__(self, platform, core_config, **kwargs):
        platform.add_extension(get_common_ios())

        # Parameters -------------------------------------------------------------------------------
        sys_clk_freq   = core_config["sys_clk_freq"]
        csr_data_width = core_config.get("csr_data_width", 32)
        csr_base       = core_config.get("csr_base", 0xF0000000)
        rate           = "1:{}".format(core_config.get("sdram_ratio", 4))

        # SoCCore ----------------------------------------------------------------------------------

        LiteXSoC.__init__(self, platform, sys_clk_freq,
            bus_standard         = "wishbone",
            bus_data_width       = 32,
            bus_address_width    = 32,
            bus_timeout          = 1e6,
            bus_bursting         = False,
            bus_interconnect     = "shared",
            bus_reserved_regions = {},

            csr_data_width       = 32,
            csr_address_width    = 14,
            csr_paging           = 0x800,
            csr_ordering         = "big",
            csr_reserved_csrs    = {},

            irq_n_irqs           = 0,
            irq_reserved_irqs    = {},
        )

        # Attributes
        self.config         = {}
        self.cpu_type       = None

        self.clk_freq       = self.sys_clk_freq

        self.csr_regions    = {}
        self.mem_regions    = self.bus.regions
        self.mem_map        = {
            "csr":  csr_base,
        }

        self.wb_slaves      = {}

        # Dummy CPU
        self.add_cpu("None")

        # Clock domain -----------------------------------------------------------------------------

        self.cd_sys = ClockDomain("sys")
        self.comb += [
            self.cd_sys.clk.eq(platform.request("clk")),
            self.cd_sys.rst.eq(platform.request("rst")),
        ]

        # DRAM Interface ---------------------------------------------------------------------------

        platform.add_extension(get_dram_ios(core_config))
        sdram_module = core_config["sdram_module"](sys_clk_freq, rate=rate)

        # Collect Electrical Settings.
        electrical_settings_kwargs = {}
        for name in ["rtt_nom", "rtt_wr", "ron"]:
            if core_config.get(name, None) is not None:
                electrical_settings_kwargs[name] = core_config[name]

        # PHY stub
        self.submodules.ddrphy = sdram_phy = PHYNone (
            memtype          = core_config["memtype"],
            nphases          = core_config.get("dfi_nphases",     4),
            addressbits      = core_config.get("dfi_addressbits", 10),
            databits         = core_config.get("sdram_data_nb",   32),
            bankbits         = core_config.get("dfi_bankbits",    2),
            nranks           = core_config.get("sdram_rank_nb",   1),
            ratio            = int(rate.split(":")[-1]),
        )
        self.expose_dfi(platform, sdram_phy.dfi)

        # Collect Controller Settings.
        controller_settings_kwargs = {}
        for name in inspect.getfullargspec(ControllerSettings. __init__).args:
            if core_config.get(name, None) is not None:
                controller_settings_kwargs[name] = core_config[name]
        controller_settings = controller_settings = ControllerSettings(**controller_settings_kwargs)

        # DRAM Controller --------------------------------------------------------------------------

        self.dram_ctrl = sdram_ctrl = DRAMCore(
            phy                     = sdram_phy,
            module                  = sdram_module,
            clk_freq                = self.sys_clk_freq,
            controller_settings     = controller_settings
        )

        # DRAM Control/Status ----------------------------------------------------------------------

        # Expose calibration status to user.
        self.submodules.ddrctrl = DRAMCoreControl()
        self.comb += platform.request("init_done").eq(self.ddrctrl.init_done.storage)
        self.comb += platform.request("init_error").eq(self.ddrctrl.init_error.storage)

        # Expose a bus control interface to user.
        wb_bus = wishbone.Interface()
        self.bus.add_master(master=wb_bus)
        platform.add_extension(wb_bus.get_ios("wb_ctrl"))
        wb_pads = platform.request("wb_ctrl")
        self.comb += wb_bus.connect_to_pads(wb_pads, mode="slave")

        # User ports -------------------------------------------------------------------------------

        for name, port in core_config["user_ports"].items():

            # Common -------------------------------------------------------------------------------
            user_enable = Signal()
            # By default, block port until controller is ready.
            if port.get("block_until_ready", True):
                self.sync += user_enable.eq(self.ddrctrl.init_done.storage & ~self.ddrctrl.init_error.storage)
            # Else never block.
            else:
                self.comb += user_enable.eq(1)

            # Request user port on crossbar and add optional ECC.
            if port["type"] in ["native", "wishbone", "axi"]:
                # With ECC.
                if port.get("ecc", False):
                    assert port.get("data_width", None) is not None
                    ecc_port  = self.dram_ctrl.crossbar.get_port()
                    user_port = LiteDRAMNativePort(
                        mode          = ecc_port.mode,
                        address_width = ecc_port.address_width,
                        data_width    = port.get("data_width")
                    )
                    ecc = LiteDRAMNativePortECC(user_port, ecc_port, with_error_injection=False)
                    setattr(self.submodules, f"ecc_{name}", ecc)
                # Without ECC.
                else:
                    user_port = self.dram_ctrl.crossbar.get_port(data_width=port.get("data_width", None))

            # Native -------------------------------------------------------------------------------
            if port["type"] == "native":
                platform.add_extension(get_native_user_port_ios(name,
                    user_port.address_width,
                    user_port.data_width))
                _user_port_io = platform.request("user_port_{}".format(name))
                self.comb += [
                    # Cmd Channel.
                    user_port.cmd.valid.eq(_user_port_io.cmd_valid & user_enable),
                    _user_port_io.cmd_ready.eq(user_port.cmd.ready & user_enable),
                    user_port.cmd.we.eq(_user_port_io.cmd_we),
                    user_port.cmd.addr.eq(_user_port_io.cmd_addr),

                    # WData Channel.
                    user_port.wdata.valid.eq(_user_port_io.wdata_valid & user_enable),
                    _user_port_io.wdata_ready.eq(user_port.wdata.ready & user_enable),
                    user_port.wdata.we.eq(_user_port_io.wdata_we),
                    user_port.wdata.data.eq(_user_port_io.wdata_data),

                    # RData Channel.
                    _user_port_io.rdata_valid.eq(user_port.rdata.valid & user_enable),
                    user_port.rdata.ready.eq(_user_port_io.rdata_ready & user_enable),
                    _user_port_io.rdata_data.eq(user_port.rdata.data),
                ]
            # Wishbone -----------------------------------------------------------------------------
            elif port["type"] == "wishbone":
                wb_port = wishbone.Interface(
                    user_port.data_width,
                    user_port.address_width)
                wishbone2native = LiteDRAMWishbone2Native(wb_port, user_port)
                self.submodules += wishbone2native
                platform.add_extension(get_wishbone_user_port_ios(name,
                        len(wb_port.adr),
                        len(wb_port.dat_w)))
                _wb_port_io = platform.request("user_port_{}".format(name))
                self.comb += [
                    wb_port.adr.eq(_wb_port_io.adr),
                    wb_port.dat_w.eq(_wb_port_io.dat_w),
                    _wb_port_io.dat_r.eq(wb_port.dat_r),
                    wb_port.sel.eq(_wb_port_io.sel),
                    wb_port.cyc.eq(_wb_port_io.cyc & user_enable),
                    wb_port.stb.eq(_wb_port_io.stb & user_enable),
                    _wb_port_io.ack.eq(wb_port.ack & user_enable),
                    wb_port.we.eq(_wb_port_io.we),
                    _wb_port_io.err.eq(wb_port.err),
                ]
            # AXI ----------------------------------------------------------------------------------
            elif port["type"] == "axi":
                axi_port  = LiteDRAMAXIPort(
                    data_width    = user_port.data_width,
                    address_width = user_port.address_width + log2_int(user_port.data_width//8),
                    id_width      = port["id_width"])
                axi2native = LiteDRAMAXI2Native(
                    axi  = axi_port,
                    port = user_port,
                    with_read_modify_write = port.get("ecc", False)
                )
                self.submodules += axi2native
                platform.add_extension(get_axi_user_port_ios(name,
                        axi_port.address_width,
                        axi_port.data_width,
                        port["id_width"]))
                _axi_port_io = platform.request("user_port_{}".format(name))
                self.comb += [
                    # AW Channel.
                    axi_port.aw.valid.eq(_axi_port_io.awvalid & user_enable),
                    _axi_port_io.awready.eq(axi_port.aw.ready & user_enable),
                    axi_port.aw.addr.eq(_axi_port_io.awaddr),
                    axi_port.aw.burst.eq(_axi_port_io.awburst),
                    axi_port.aw.len.eq(_axi_port_io.awlen),
                    axi_port.aw.size.eq(_axi_port_io.awsize),
                    axi_port.aw.id.eq(_axi_port_io.awid),

                    # W Channel.
                    axi_port.w.valid.eq(_axi_port_io.wvalid),
                    _axi_port_io.wready.eq(axi_port.w.ready),
                    axi_port.w.last.eq(_axi_port_io.wlast),
                    axi_port.w.strb.eq(_axi_port_io.wstrb),
                    axi_port.w.data.eq(_axi_port_io.wdata),

                    # B Channel.
                    _axi_port_io.bvalid.eq(axi_port.b.valid),
                    axi_port.b.ready.eq(_axi_port_io.bready),
                    _axi_port_io.bresp.eq(axi_port.b.resp),
                    _axi_port_io.bid.eq(axi_port.b.id),

                    # AR Channel.
                    axi_port.ar.valid.eq(_axi_port_io.arvalid & user_enable),
                    _axi_port_io.arready.eq(axi_port.ar.ready & user_enable),
                    axi_port.ar.addr.eq(_axi_port_io.araddr),
                    axi_port.ar.burst.eq(_axi_port_io.arburst),
                    axi_port.ar.len.eq(_axi_port_io.arlen),
                    axi_port.ar.size.eq(_axi_port_io.arsize),
                    axi_port.ar.id.eq(_axi_port_io.arid),

                    # R Channel.
                    _axi_port_io.rvalid.eq(axi_port.r.valid),
                    axi_port.r.ready.eq(_axi_port_io.rready),
                    _axi_port_io.rlast.eq(axi_port.r.last),
                    _axi_port_io.rresp.eq(axi_port.r.resp),
                    _axi_port_io.rdata.eq(axi_port.r.data),
                    _axi_port_io.rid.eq(axi_port.r.id),
                ]
            # FIFO ---------------------------------------------------------------------------------
            elif port["type"] == "fifo":
                data_width = port.get("data_width", self.sdram.crossbar.controller.data_width)
                platform.add_extension(get_fifo_user_port_ios(name, data_width))
                _user_fifo_io = platform.request("user_fifo_{}".format(name))
                fifo = LiteDRAMFIFO(
                    data_width      = data_width,
                    base            = port["base"],
                    depth           = port["depth"],
                    write_port      = self.sdram.crossbar.get_port("write"),
                    read_port       = self.sdram.crossbar.get_port("read"),
                    with_bypass     = True,
                )
                self.submodules += fifo
                self.comb += [
                    # In.
                    fifo.sink.valid.eq(_user_fifo_io.in_valid & user_enable),
                    _user_fifo_io.in_ready.eq(fifo.sink.ready & user_enable),
                    fifo.sink.data.eq(_user_fifo_io.in_data),

                    # Out.
                    _user_fifo_io.out_valid.eq(fifo.source.valid & user_enable),
                    fifo.source.ready.eq(_user_fifo_io.out_ready & user_enable),
                    _user_fifo_io.out_data.eq(fifo.source.data),
                ]
            else:
                raise ValueError("Unsupported port type: {}".format(port["type"]))

    def expose_dfi(self, platform, dfi):
        """
        Exposes the provided DFI interface by creating a platform extension with
        pads that match the DFI. Connects DFI to the pads
        """

        # Add DFI pads
        extension = ["dfi", 0]
        for name, signal in dfi.get_standard_names():
            name = name.replace("dfi_", "")
            extension.append(Subsignal(name, Pins(len(signal))))
        platform.add_extension([tuple(extension)])

        # Connect DFI pads
        pads = platform.request("dfi")
        for name, signal in dfi.get_standard_names(s2m=False):
            name = name.replace("dfi_", "")
            pad = getattr(pads, name)
            self.comb += pad.eq(signal)

        for name, signal in dfi.get_standard_names(m2s=False):
            name = name.replace("dfi_", "")
            pad = getattr(pads, name)
            self.comb += signal.eq(pad)

# Build --------------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="DRAM standalone core generator")

    parser.add_argument(
        "config",
        type=str,
        help="YAML config file"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="build",
        help="Base Output directory."
    )
    parser.add_argument(
        "--name",
        type=str,
        default="dram_ctrl",
        help="Standalone core/module name"
    )

    args = parser.parse_args()

    # Load the config
    core_config = yaml.load(open(args.config).read(), Loader=yaml.Loader)

    # Convert YAML elements to Python/LiteX --------------------------------------------------------
    for k, v in core_config.items():
        replaces = {"False": False, "True": True, "None": None}
        for r in replaces.keys():
            if v == r:
                core_config[k] = replaces[r]
        if "clk_freq" in k:
            core_config[k] = float(core_config[k])
        if k == "sdram_module":
            core_config[k] = getattr(litedram_modules, core_config[k])

    # Generate core --------------------------------------------------------------------------------

    builder_arguments = {
        "output_dir":       args.output_dir,
        "gateware_dir":     None,
        "software_dir":     None,
        "include_dir":      None,
        "generated_dir":    None,
        "compile_software": False,
        "compile_gateware": False,
        "csr_csv":          os.path.join(args.output_dir, "csr.csv")
    }

    platform = NoPlatform("", io=[])
    soc     = DRAMCoreSoC(platform, core_config)
    builder = Builder(soc, **builder_arguments)
    builder.build(build_name=args.name, regular_comb=False)

if __name__ == "__main__":
    main()
