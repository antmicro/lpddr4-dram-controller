# Copyright (c) 2025 Antmicro <www.antmicro.com>
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations
from collections import OrderedDict, deque
from enum import Enum, auto
from logging import Logger
import re
import string
from typing import Callable, Iterator, Optional

from pyuvm import ConfigDB
import cocotb.utils
from cocotb.triggers import RisingEdge, ClockCycles, FallingEdge
from cocotb.types import Range
from cocotb.binary import LogicArray

from common import DRAMWriteItem, DRAMReadItem


class CommandType(Enum):
    MPC = ("L L L L L OP6", "OP0 OP1 OP2 OP3 OP4 OP5")
    PRE = ("L L L L H AB", "BA0 BA1 BA2 V V V")
    REF = ("L L L H L AB", "BA0 BA1 BA2 V V V")
    SRE = ("L L L H H V", "V V V V V V")
    WR1 = ("L L H L L BL", "BA0 BA1 BA2 V C9 AP")
    SRX = ("L L H L H V", "V V V V V V")
    MWR1 = ("L L H H L L", "BA0 BA1 BA2 V C9 AP")
    RD1 = ("L H L L L BL", "BA0 BA1 BA2 V C9 AP")
    CAS2 = ("L H L L H C8", "C2 C3 C4 C5 C6 C7")
    MRW1 = ("L H H L L OP7", "MA0 MA1 MA2 MA3 MA4 MA5")
    MRW2 = ("L H H L H OP6", "OP0 OP1 OP2 OP3 OP4 OP5")
    MRR1 = ("L H H H L V", "MA0 MA1 MA2 MA3 MA4 MA5")
    ACT1 = ("H L R12 R13 R14 R15", "BA0 BA1 BA2 R16 R10 R11")
    RFU1 = ("L L H H H V", "V V V V V V")
    RFU2 = ("L H L H L V", "V V V V V V")
    RFU3 = ("L H L H H V", "V V V V V V")
    RFU4 = ("L H H H H V", "V V V V V V")
    ACT2 = ("R17 R18 R6 R7 R8 R9", "R0 R1 R2 R3 R4 R5")


# FIXME: We don't actually implement most of these
class TimingType(Enum):
    tRP = auto()  # should support tRPab and tRPpb instead
    tRCD = auto()
    tWR = auto()
    tWTR = auto()
    tREFI = auto()
    tRFC = auto()
    tFAW = auto()
    tCCD = auto()
    tRRD = auto()
    tRC = auto()
    tRAS = auto()
    tSR = auto()
    tXSR = auto()
    tXP = auto()
    tRTP = auto()
    tPPD = auto()
    tRPpb = auto()
    tRPab = auto()


class Command:
    """
    DRAM command
    """

    def __init__(self, type: CommandType, time=None):
        if time is None:
            time = int(cocotb.utils.get_sim_time("ps"))

        self.type = type
        self.time = time
        self.args = OrderedDict[str, int]()

    def __str__(self):
        s = "[[{}, t = {:10d}".format(self.type.name, self.time)
        added = []
        for k, v in self.args.items():
            if k.endswith(tuple(*string.digits.split())):
                key = re.sub(r"[0-9]+", "", k)
                if key in added:
                    continue
                added.append(key)
                s += f", {key} = 0x{self.get_total_arg(key):X}"
            else:
                s += f", {k} = {v}"
        return s + "]]"

    def get_total_arg(self, key: str) -> int:
        total = 0
        for arg, val in self.args.items():
            if arg.startswith(key.strip()):
                n = int(arg[len(key.strip()) :])
                total |= val << n
        return total


class Bank:
    """
    Bank state
    """

    def __init__(self):
        self.is_active = False
        self.row = None
        self.refreshed_at = -1
        self.can_refresh = True

    def precharge(self):
        self.is_active = False
        self.row = None

    def refresh(self, all_banks: bool = False):
        assert all_banks or self.can_refresh
        self.refreshed_at = cocotb.utils.get_sim_time("ps")
        self.can_refresh = all_banks

    def activate(self, row: int):
        assert not self.is_active
        self.is_active = True
        self.row = row


class TimingRule:
    """
    DRAM command timing rule helper.

    This class gets fed a stream of incoming LPDDR4 commands through `self.pipe_command()`.
    It applies `self.left_filter` to each command and if it return True
    enqueues such a command in `self.lefts`. Then after receiving a next command,
    `self.right_filter` is called for each pair of (current_cmd, enqueued_cmd) for all
    enqueued commands. If right_filter returns True then a timing check match was found
    and a pair of commands that should be verified is yielded to the calling function.
    """

    class NonUniqueError(Exception):
        def __init__(self, rule: TimingRule, *args):
            super().__init__(*args)
            self.rule = rule

    def __init__(
        self,
        left_filter: Callable[[Command], bool],
        right_filter: Callable[[Command, Command], bool],
        timing: TimingType,
        enforce_unique: bool = False,
    ):
        self.left_filter = left_filter
        self.right_filter = right_filter
        self.timing = timing
        self.enforce_unique = enforce_unique
        self.lefts = list[Command]()

    def pipe_command(self, cmd: Command) -> Iterator[tuple[Command, Command]]:
        if self.left_filter(cmd):
            if self.enforce_unique and len(self.lefts) > 0:
                raise self.NonUniqueError(self)
            self.lefts.append(cmd)

        for lcmd in self.lefts[:]:
            if cmd is not lcmd:
                if self.right_filter(cmd, lcmd):
                    self.lefts.remove(lcmd)
                    yield (lcmd, cmd)


class Timings:
    """
    DRAM timings progammable in the controller
    """

    def __init__(self, uvm_context=None, uvm_inst_name=""):
        self.uvm_context = uvm_context

    def __getitem__(self, item: object) -> int:
        if not isinstance(item, TimingType):
            raise IndexError
        value = ConfigDB().get(self.uvm_context, "", item.name, default=None)
        if value is not None:
            return value
        return 0


class TimingChecker:
    """
    A helper class that tracks commands and checks if provided timings are
    correctly enforced.
    """

    def istype(*type: CommandType):
        return lambda c, *_: c.type in type

    def istype_and_bank_match(*type: CommandType):
        return lambda r, l: r.type in type and (
            r.args.get("AB") == 1 or r.get_total_arg("BA") == l.get_total_arg("BA")
        )

    def has_pre_pb(cmd: Command):
        if cmd.type is CommandType.PRE and cmd.args["AB"] == 0:
            return True
        elif (
            cmd.type in [CommandType.RD1, CommandType.WR1, CommandType.MWR1] and cmd.args["AP"] == 1
        ):
            return True
        return False

    C = CommandType
    T = TimingType

    # Can't really do tWR and tWTR, they depend on DDR data signals
    RULES: list[TimingRule] = [
        TimingRule(istype(C.ACT2), istype_and_bank_match(C.ACT2), T.tRC),
        TimingRule(istype(C.SRE), istype(C.SRX), T.tSR, True),
        TimingRule(istype(C.SRX), lambda *_: True, T.tXSR, True),
        TimingRule(
            istype(C.RD1, C.WR1, C.MWR1), istype_and_bank_match(C.RD1, C.WR1, C.MWR1), T.tCCD
        ),
        TimingRule(istype(C.ACT2), istype_and_bank_match(C.RD1, C.WR1, C.MWR1), T.tRCD),
        TimingRule(has_pre_pb, istype_and_bank_match(C.ACT2, C.REF), T.tRPpb, True),
        TimingRule(istype(C.ACT2), istype_and_bank_match(C.PRE), T.tRAS),
        TimingRule(istype(C.PRE), istype(C.PRE), T.tPPD),
        TimingRule(
            istype(C.REF), istype_and_bank_match(C.REF, C.PRE, C.ACT2, C.RD1, C.WR1, C.MWR1), T.tRFC
        ),
        TimingRule(
            lambda c: c.type is CommandType.PRE and c.args["AB"] == 1,
            istype(C.ACT2, C.REF),
            T.tRPab,
        ),
        TimingRule(
            istype(C.ACT2),
            lambda r, l: r.type in [CommandType.ACT2, CommandType.REF]
            and r.get_total_arg("BA") != l.get_total_arg("BA"),
            TimingType.tRRD,
        ),
    ]

    def __init__(self, clk_freq, cke, cs_n, logger):
        self.rules = []
        self.cmd_time = dict()
        self.logger = logger
        self.clk_freq = clk_freq
        self.passed = True

        cocotb.start_soon(self.tXP_verifier(cke, cs_n))
        cocotb.start_soon(self.tFAW_verifier())
        cocotb.start_soon(self.tREFI_verifier())

    async def tXP_verifier(self, cke, cs_n):
        while True:
            await RisingEdge(cke)
            time = cocotb.utils.get_sim_time("ps")
            await FallingEdge(cs_n)
            delta = cocotb.utils.get_sim_time("ps") - time
            expected = Timings(None)[TimingType.tXP] * 1e6 // self.clk_freq
            if delta < expected:
                self.logger.error("tXP violation. Expected >=%f, actual: %f", expected, delta)
                self.passed = False

    async def tFAW_verifier(self):
        # TODO: verify tFAW
        pass

    async def tREFI_verifier(self):
        # TODO: verify tREFI
        pass

    def verify_time(self, cmd1: Command, cmd2: Command, timing: TimingType):
        delay = cmd2.time - cmd1.time
        assert delay > 0
        expected = Timings(None)[timing] * 1e6 // self.clk_freq
        if delay < expected:
            self.logger.error(
                "%s timing violation between %s and %s. Should be >=%f but is %f",
                timing.name, cmd1, cmd2, expected, delay
            )
            self.passed = False

    def push_command(self, cmd: Command):
        assert cmd.type is not CommandType.CAS2, "CAS2 should've been merged with its consumer"
        for rule in self.RULES:
            try:
                for left, right in rule.pipe_command(cmd):
                    self.verify_time(left, right, rule.timing)
            except TimingRule.NonUniqueError as e:
                self.logger.error(
                    "%s timing violation after %s. This rule requires event uniqueness.",
                    e.rule.timing.name, e.rule.lefts[0]
                )
                self.passed = False


# =============================================================================


class LPDDR4Model:
    """
    PHY+DRAM model. Parses DFI commands and read/write requests.
    """

    def __init__(self, iface, logger: Logger, with_storage=False):
        self.iface = iface
        self.logger = logger
        self.passed = True

        self.with_storage = with_storage
        self.storage = dict()

        # Get parameters
        self.clk_freq = float(ConfigDB().get(None, "", "CLK_FREQ"))
        self.timings = Timings(None, "")
        self.cl = ConfigDB().get(None, "", "CL")
        self.wr_lat = ConfigDB().get(None, "", "WR_LAT")

        # Create the timing checker
        self.timing_checker = TimingChecker(
            self.clk_freq, iface.dfi_cke, iface.dfi_cs_n, self.logger
        )

        # TODO: Get DFI signal width
        self.banks = {b: Bank() for b in range(1 << 3)}
        self.queue = deque[Command]()

        self.pending_subcommand: Optional[int] = None
        self.pending_act1: Optional[Command] = None
        self.pending_cas2_consumer: Optional[Command] = None

        self.ap = None

    async def tick(self):
        """
        Worker function. Call every rising edge of DFI clock
        """

        if not self.iface.dfi_reset_n.value:
            return

        if self.iface.dfi_cs_n.value:
            if self.pending_subcommand is not None:
                self.logger.error(
                    "CS was high on two consecutive clock cycles. It should be "
                    "high on the first one, and low on the next one, each one "
                    "corresponding to one half of a command on the CA bus."
                )
                self.passed = False
                return
            self.pending_subcommand = self.iface.dfi_address.value
            return

        if ca1 := self.pending_subcommand:
            self.pending_subcommand = None
            ca2 = self.iface.dfi_address.value
            cmd = self.parse_dfi_command(ca1, ca2)
            if cmd is not None:
                self.handle_dfi_command(cmd)

        return await self.handle_dfi_io()

    def handle_dfi_command(self, cmd: Command):
        for prev, expected in [
            (self.pending_act1, CommandType.ACT2),
            (self.pending_cas2_consumer, CommandType.CAS2),
        ]:
            if prev is not None and cmd.type is not expected:
                self.logger.error(
                    f"{prev.type.name} command MUST BE immediately followed by an {expected.name}"
                    f" command. Instead, it was followed by: {cmd.type.name}"
                )
                self.passed = False
                return

        match cmd.type:
            case CommandType.PRE:
                ab = cmd.args["AB"]
                ba = cmd.get_total_arg("BA")
                for bank in self.banks.values() if ab else [self.banks[ba]]:
                    bank.precharge()

            case CommandType.ACT1:
                self.pending_act1 = cmd

            case CommandType.ACT2:
                if self.pending_act1 is None:
                    self.logger.error("An ACT-2 commands was issued without an earlier ACT-1")
                    self.passed = False
                    return
                cmd.args.update(self.pending_act1.args)
                self.pending_act1 = None
                bank = cmd.get_total_arg("BA")
                if self.banks[bank].is_active:
                    self.logger.error(
                        "After a bank has been ACT it must be PRE, before another"
                        " ACT command can be applied"
                    )
                    self.passed = False
                    return
                self.banks[bank].activate(cmd.get_total_arg("R"))

            case CommandType.REF:
                if cmd.args["AB"] == 1:
                    if any(b.is_active for b in self.banks.values()):
                        self.logger.error("An all-bank REF command requires all banks to be idle")
                        self.passed = False
                    for bank in self.banks.values():
                        bank.refresh(True)
                else:
                    bank = cmd.get_total_arg("BA")
                    if not self.banks[bank].can_refresh:
                        self.logger.error(
                            f"Refresh for bank {bank} has been requested again, before "
                            "all banks were refreshed"
                        )
                    self.banks[bank].refresh()
                # All 8 banks have been refreshed
                if not any(b.can_refresh for b in self.banks.values()):
                    for bank in self.banks.values():
                        bank.can_refresh = True

            case CommandType.WR1 | CommandType.RD1:
                if self.iface.dfi_cke.value != 1:
                    # Shouldn't this be true for every single command actually?
                    # The JEDEC spec for some reason though focuses on it being asserted
                    # in the context of read and write access operations.
                    self.logger.error("The CKE signal has to be asserted on RD and WR cmds")
                    self.passed = False
                    return

                self.pending_cas2_consumer = cmd
                return  # don't push to timing checker, do it after CAS2 is received

            case CommandType.CAS2:
                if self.pending_cas2_consumer is None:
                    self.logger.error(
                        "CAS-2 command was issued, but the previous command did not require it"
                    )
                    self.passed = False
                    return

                self.pending_cas2_consumer.args.update(cmd.args)
                self.pending_cas2_consumer.time = cmd.time
                cmd = self.pending_cas2_consumer
                self.pending_cas2_consumer = None
                bank = cmd.get_total_arg("BA")

                if cmd.type in [CommandType.WR1, CommandType.MWR1]:
                    if cmd.get_total_arg("C") & 0b1111 != 0:
                        self.logger.error("For WR1 and MWR1 C[3:2] must be driven low")
                        self.passed = False
                        return

                if not self.banks[bank].is_active:
                    self.logger.error(f"Attempted to {cmd.type.name} to an inactive bank {bank}")
                    self.passed = False
                    return

                self.queue.append(cmd)

                if cmd.args["AP"] == 1:
                    self.banks[bank].precharge()

            case CommandType.MWR1:
                # TODO: Check how to exactly handle masked write
                self.logger.error(f"Masked write is not supported for now and should not be used")
                self.passed = False
                return

            case _:
                self.logger.warning(f"The {cmd.type} command is not handled in the testbench")

        self.timing_checker.push_command(cmd)
        self.passed &= self.timing_checker.passed

    def parse_dfi_command(self, CA1: int, CA2: int) -> Optional[Command]:
        """
        Parses a command sent to DRAM over DFI
        """

        def sig_matches_truth(ca: int, truth: str) -> Optional[dict[str, int]]:
            args = dict[str, int]()
            bits = truth.split(" ")
            for i in range(6):
                ca_bit = (ca >> i) & 1
                if bits[i] == "H" and ca_bit != 1:
                    return None
                elif bits[i] == "L" and ca_bit != 0:
                    return None
                elif bits[i] not in ["V", "H", "L"]:
                    args[bits[i]] = ca_bit
            else:
                return args

        for cmd in CommandType if self.pending_act1 is None else [CommandType.ACT2]:
            ca1args = sig_matches_truth(CA1, cmd.value[0])
            ca2args = sig_matches_truth(CA2, cmd.value[1])
            if ca1args is not None and ca2args is not None:
                cmd = Command(cmd)
                cmd.args = {**ca1args, **ca2args}
                return cmd

        self.logger.error(f"Unknown LPDDR4 command on the CA bus: {bin(CA1)}, {bin(CA2)}")
        self.passed = False
        return None

    async def report_dfi_write(self):
        """
        Checks DFI signals after `self.wr_lat` cycles and sends them to the
        parent monitor analysis port. This should be spawned as a separate
        coroutine.
        """

        await ClockCycles(self.iface.dfi_clk, self.wr_lat)

        data = self.iface.dfi_wrdata.value
        mask = self.iface.dfi_wrdata_mask.value

        # Check and pop write command
        if not len(self.queue) or self.queue[0].type is not CommandType.WR1:
            self.logger.error("DFI write without pending DRAM write command")
            self.passed = False
            return None

        cmd = self.queue.popleft()
        bank = self.banks[cmd.get_total_arg("BA")]

        if not bank.is_active:
            self.logger.error("DFI write to an inactive bank: %d", cmd.get_total_arg("BA"))
            self.passed = False
            return None

        self.logger.debug(
            "{} row=0x{:04X} data=0x{:08X} mask=0x{:02X}".format(
                cmd, bank.row, data.integer, mask.integer
            )
        )

        if self.with_storage:
            for i in range(data.n_bits // 8):
                if (mask.integer & (1 << i)) == 0:
                    key = (bank.row, cmd.get_total_arg("BA"), cmd.get_total_arg("C"), i)
                    self.storage[key] = (data.integer >> (8 * i)) & 0xFF

        data = LogicArray(data, Range(data.n_bits - 1, "downto", 0))
        item = DRAMWriteItem(cmd.get_total_arg("BA"), bank.row, cmd.get_total_arg("C"), data, mask)
        # self.logger.info("DFI WRITE: (R: %x, B: %x, C: %x)[%x] = %x", bank.row, cmd.get_total_arg("BA"), cmd.get_total_arg("C"), DFIScoreboard.decode_dram_address(item), data.integer)
        self.ap.write(item)

    async def handle_dfi_io(self):
        """
        Handles DFI data operations. Upon a successful write detection returns
        its DRAM address, data and mask
        """

        if self.iface.dfi_wrdata_en.value:
            await cocotb.start(self.report_dfi_write())

            return ["WR"]

        if self.iface.dfi_rddata_en.value:
            if not len(self.queue) or self.queue[0].type != CommandType.RD1:
                self.logger.error("DFI read without pending DRAM read command")
                self.passed = False
                return

            cmd = self.queue.popleft()
            bank = self.banks[cmd.get_total_arg("BA")]

            if not bank.is_active:
                self.logger.error("DFI read from an inactive bank: %d", cmd.get_total_arg("BA"))
                self.passed = False
                return None

            data_bits = self.iface.dfi_rddata.value.n_bits
            if self.with_storage:
                data = 0
                for i in reversed(range(data_bits // 8)):
                    key = (bank.row, cmd.get_total_arg("BA"), cmd.get_total_arg("C"), i)
                    dat = self.storage.get(key, 0x00)
                    data |= dat << (8 * i)
                data = LogicArray(data, Range(data_bits - 1, "downto", 0))
            else:
                data = LogicArray(0, Range(data_bits - 1, "downto", 0))

            item = DRAMReadItem(cmd.get_total_arg("BA"), bank.row, cmd.get_total_arg("C"), data)
            # self.logger.info("DFI READ: (R: %x, B: %x, C: %x)[%x] = %x", bank.row, cmd.get_total_arg("BA"), cmd.get_total_arg("C"), DFIScoreboard.decode_dram_address(item), data.integer)

            return "RD", cmd.get_total_arg("BA"), bank.row, cmd.get_total_arg("C"), data
