# Copyright (c) 2023 Antmicro <www.antmicro.com>
# SPDX-License-Identifier: Apache-2.0

"""
DRAM model.

Models PHY+DRAM as a whole. Parses DRAM commands and decodes read/write
requests. Can simulate the memory storage. The model includes a timing checker
which ensures that command timings are met.
"""

from collections import OrderedDict

from pyuvm import ConfigDB
import cocotb.utils

# =============================================================================


class Command:
    """
    DRAM command
    """

    def __init__(self, name, time = None):

        if time is None:
            time = int(cocotb.utils.get_sim_time('ps'))

        self.name   = name
        self.time   = time
        self.args   = OrderedDict()

    def __str__(self):
        s = "t={:10d} {:<4}".format(self.time, self.name)

        for k, v in self.args.items():
            if k in ["row", "col"]:
                vstr = "0x{:04X}".format(v)
            else:
                vstr = str(v)
            s += " {}={}".format(k, vstr)

        return s

    def __repr__(self):
        return str(self)


class Bank:
    """
    Bank state
    """

    def __init__(self):
        self.is_active  = False
        self.row        = None


class TimingRule:
    """
    DRAM command timing rule. Delay expressed in ps
    """

    def __init__(self, name, prev, curr, delay):
        self.name  = name
        self.prev  = prev
        self.curr  = curr
        self.delay = delay

    def __str__(self):
        return "{}={:.2f}ns ({}->{})".format(
            self.name,
            1e-3 * self.delay,
            self.prev,
            self.curr
        )

    def __repr__(self):
        return str(self)


class Timings:
    """
    DRAM timings progammable in the controller
    """

    # Timing names
    TIMINGS = {
        "tRP",
        "tRCD",
        "tWR",
        "tWTR",
        "tREFI",
        "tRFC",
        "tFAW",
        "tCCD",
        "tRRD",
        "tRC",
        "tRAS",
        "tZQCS",
    }

    def __init__(self, uvm_context=None, uvm_inst_name="*"):
        for timing in self.TIMINGS:
            value = ConfigDB().get(uvm_context, uvm_inst_name, timing)
            setattr(self, timing, int(value))

# =============================================================================


class TimingChecker:
    """
    A helper class that tracks commands and checks if provided timings are
    correctly enforced.
    """

    RULES = [
        # tRP
        ("PRE",  "ACT", "tRP"),
        ("PRE",  "REF", "tRP"),
        # tRCD
        ("ACT",  "WR",  "tRCD"),
        ("ACT",  "RD",  "tRCD"),
        # tRAS
        ("ACT",  "PRE", "tRAS"),
        # tRFC
        ("REF",  "PRE", "tRFC"),
        ("REF",  "ACT", "tRFC"),
        # tCCD
        ("WR",   "RD",  "tCCD"),
        ("WR",   "WR",  "tCCD"),
        ("RD",   "RD",  "tCCD"),
        ("RD",   "WR",  "tCCD"),
        # tRC
        ("ACT",  "ACT", "tRC"),
        # tWR
        ("WR",   "PRE", "tWR"),
        # tWTR
        ("WR",   "RD",  "tWTR"),
        # tZQCS
        ("ZQCS", "ACT", "tZQCS"),
    ]

    def __init__(self, timings, clk_freq, logger):
        self.rules    = []
        self.cmd_time = dict()
        self.logger   = logger

        # Initialize rules
        for rule in self.RULES:
            delay_cyc = getattr(timings, rule[2])
            delay_tim = int(1e6 * delay_cyc / clk_freq) # [ps]
            self.rules.append(TimingRule(rule[2], rule[0], rule[1], delay_tim))

            # PRE = PREA
            if rule[0] == "PRE" or rule[1] == "PRE":
                prev = rule[0].replace("PRE", "PREA")
                curr = rule[1].replace("PRE", "PREA")
                self.rules.append(TimingRule(rule[2], prev, curr, delay_tim))

        self.list_rules()

    def list_rules(self):
        """
        Outputs the list of timing tules through the logger
        """
        for rule in self.rules:
            self.logger.info(str(rule))

    def check_command(self, cmd):
        """
        Check if the command meets timings w.r.t. previous commands
        """

        # Check rules
        result = True
        for rule in self.rules:

            if cmd.name != rule.curr:
                continue

            # No previous command, this is the first one
            prev_time = self.cmd_time.get(rule.prev, None)
            if prev_time is None:
                continue

            delay = cmd.time - prev_time

            # Debug
            self.logger.debug("{}, actual={:.2f}ns".format(
                str(rule),
                1e-3 * delay
            ))

            # Check
            if delay < rule.delay:
                result = False
                self.logger.error("Timing rule {} violated, actual={:.2f}ns".format(
                    str(rule),
                    1e-3 * delay
                ))

        # Store the command time
        self.cmd_time[cmd.name] = cmd.time
        return result


# =============================================================================


class Model:
    """
    PHY+DRAM model. Parses DFI commands and read/write requests.
    """

    COMMANDS = {
        # RAS, CAS, WE
        (0, 0, 0): "MRS",
        (0, 0, 1): "REF",
        (0, 1, 0): "PRE",
        (0, 1, 1): "ACT",
        (1, 0, 0): "WR",
        (1, 0, 1): "RD",
        (1, 1, 1): "NOP",
        (1, 1, 0): "ZQC",
    }

    def __init__(self, iface, logger):
        self.iface  = iface
        self.logger = logger
        self.passed = True

        # Get parameters
        self.clk_freq = float(ConfigDB().get(None, "", "CLK_FREQ"))
        self.timings  = Timings(None, "")

        # Create the timing checker
        self.timing_checker = TimingChecker(self.timings, self.clk_freq, self.logger)

        # TODO: Get DFI signal width
        self.banks  = {b: Bank() for b in range(1 << 3)}
        self.writes = []

    async def tick(self):
        """
        Worker function. Call every rising edge of DFI clock
        """

        # In reset
        if not self.iface.dfi_reset_n.value:
            return

        # Get DFI command
        cmd = self.parse_dfi_command()
        if cmd:

            # Debug
            if cmd.name != "NOP":
                self.logger.info(str(cmd))

            # Check timing violations
            if cmd.name != "NOP":
                self.passed &= self.timing_checker.check_command(cmd)

            # Handle the command
            if cmd.name == "ACT":
                bank = self.banks[cmd.args["bank"]]

                if bank.is_active and bank.row == cmd.args["row"]:
                    self.logger.warning("Attempted to activate an active bank/row")

                bank.is_active  = True
                bank.row        = cmd.args["row"]

            elif cmd.name == "PRE":

                bank = self.banks[cmd.args["bank"]]
                bank.is_active  = False
                bank.row        = None

            elif cmd.name == "PREA":

                    for bank in self.banks.values():
                        bank.is_active  = False
                        bank.row        = None

            elif cmd.name == "WR":
                bank = self.banks[cmd.args["bank"]]

                if not bank.is_active:
                    self.logger.warning("Attempted to write to an inactive bank")
                    self.passed = False

                self.writes.append(cmd)

        # Handle DFI write
        res = self.handle_dfi_write()
        if res:
            return ("WR", *res)

        return None

    def parse_dfi_command(self):
        """
        Parses a command sent to DRAM over DFI
        """

        # CKE=0 or CSn=1
        if not self.iface.dfi_cke.value or self.iface.dfi_cs_n.value:
            return None

        # Identify the command
        cmd_sig = (
            int(self.iface.dfi_ras_n.value),
            int(self.iface.dfi_cas_n.value),
            int(self.iface.dfi_we_n.value),
        )

        cmd_name = self.COMMANDS.get(cmd_sig, None)
        if cmd_name is None:
            self.logger.error("Unknown command code {}".format(cmd_sig))
            self.passed = False
            return None

        ba = int(self.iface.dfi_bank.value)

        # Make the command
        cmd = Command(cmd_name)

        if cmd.name in ["MRS", "ACT", "RD", "WR"]:
            cmd.args["bank"] = ba

        if cmd.name == "PRE":
            a10 = bool(self.iface.dfi_address.value & (1 << 10))
            if not a10:
                cmd.args["bank"] = ba
            else:
                cmd.name += "A"

        if cmd.name == "ACT":
            cmd.args["row"] = int(self.iface.dfi_address.value)

        if cmd.name in ["RD", "WR"]:
            cmd.args["col"] = int(self.iface.dfi_address.value & 0xFFF)
            cmd.args["burst"] = "BL8" if (self.iface.dfi_address.value & 1 << 12) else "BC4"

        if cmd.name == "ZQC":
            if self.iface.dfi_address.value & (1 << 10):
                cmd.name += "L"
            else:
                cmd.name += "S"

        # TODO: Parse others if relevant

        return cmd

    def handle_dfi_write(self):
        """
        Handles DFI data writes. Upon a successful write detection returns its
        DRAM address, data and mask
        """

        if not self.iface.dfi_wrdata_en.value:
            return None

        data = int(self.iface.dfi_wrdata)
        mask = int(self.iface.dfi_wrdata_mask)

        # Check and pop write command
        if not len(self.writes) or self.writes[0].name != "WR":
            self.logger.error("DFI write without pending DRAM write command")
            self.passed = False
            return None

        cmd = self.writes[0]
        self.writes = self.writes[1:]

        # Check if the bank is active
        bank = self.banks[cmd.args["bank"]]

        if not bank.is_active:
            self.logger.error("DFI write to an inactive bank")
            return

        # Write
        self.logger.info("{} row=0x{:04X} data=0x{:08X} mask=0x{:02X}".format(
            cmd,
            bank.row,
            data,
            mask
        ))

        return (cmd.args["bank"], bank.row, cmd.args["col"], data, mask,)