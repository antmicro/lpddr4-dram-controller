# Copyright (c) 2024 Antmicro <www.antmicro.com>
# SPDX-License-Identifier: Apache-2.0

import random

from pyuvm import uvm_sequence_item

# =============================================================================


class BusWriteItem(uvm_sequence_item):
    """
    A generic data bus write request / response
    """

    def __init__(self, addr, data):
        super().__init__("{:08X}:{:08X}".format(addr, int(data)))
        self.addr = addr
        self.data = data

    def randomize(self):
        pass


class BusRandomWriteItem(uvm_sequence_item):
    """
    A randomized data bus write request / response. Randomizes data and
    address. Valid address range must be provided
    """

    def __init__(self, addr_range):
        super().__init__("bus_random_write_item")
        self.addr_range = addr_range
        self.addr = None
        self.data = None

    def randomize(self):
        self.addr = random.randint(*self.addr_range) & ~0x3
        self.data = random.randint(0x00000000, 0xFFFFFFFF)


class BusReadItem(uvm_sequence_item):
    """
    A generic data bus read request / response
    """

    def __init__(self, addr, data=None):
        super().__init__("{:08X}".format(addr))
        self.addr = addr
        self.data = data

    def randomize(self):
        pass


class BusRandomReadItem(uvm_sequence_item):
    def __init__(self, addr_range):
        super().__init__("bus_random_read_item")
        self.addr_range = addr_range
        self.addr = None
        self.data = None

    def randomize(self):
        self.addr = random.randint(*self.addr_range) & ~0x3


class WaitItem(uvm_sequence_item):
    """
    A generic wait item. Used to instruct a driver to wait N cycles
    """

    def __init__(self, cycles):
        super().__init__("@{}".format(cycles))
        self.cycles = cycles

    def randomize(self):
        pass


class DRAMWriteItem(uvm_sequence_item):
    """
    DRAM write item, conveys arguments of DFI write command
    """

    def __init__(self, bank, row, col, data, mask):
        super().__init__(
            "WR:{:02X}_{:04X}_{:03X}_{:016X}_{:02X}".format(
                bank, row, col, int(data), int(mask)
            )
        )
        self.bank = bank
        self.row = row
        self.col = col
        self.data = data
        self.mask = mask


class DRAMReadItem(uvm_sequence_item):
    """
    DRAM read item, conveys arguments of DFI read command
    """

    def __init__(self, bank, row, col, data):
        super().__init__(
            "RD:{:02X}_{:04X}_{:03X}_{:016X}".format(bank, row, col, int(data))
        )
        self.bank = bank
        self.row = row
        self.col = col
        self.data = data
