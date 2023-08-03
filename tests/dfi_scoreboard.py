from pyuvm import *

from testbench import BusReadItem, BusRandomReadItem, DRAMReadItem
from testbench import BusWriteItem, BusRandomWriteItem, DRAMWriteItem

# =============================================================================

class DFIScoreboard(uvm_component):
    """
    Base DFI scoreboard class. Provides common functionality for
    WriteScoreboard and ReadScoreboard.
    """

    def __init__(self, name, parent):
        super().__init__(name, parent)
        self.passed = True

    def build_phase(self):
        self.bus_fifo   = uvm_tlm_analysis_fifo("bus_fifo", self)
        self.dfi_fifo   = uvm_tlm_analysis_fifo("dfi_fifo", self)

        self.bus_port   = uvm_get_port("bus_port", self)
        self.dfi_port   = uvm_get_port("dfi_port", self)

    def connect_phase(self):
        self.bus_port.connect(self.bus_fifo.get_export)
        self.dfi_port.connect(self.dfi_fifo.get_export)

    @staticmethod
    def decode_dram_address(dfi_item):

        # Build DRAM address
        # TODO: Parametrize / extract this data somehow
        row_nb = 13
        col_nb = 10
        bank_nb = 3

        row_mask  = (1 << row_nb ) - 1
        col_mask  = (1 << col_nb ) - 1
        bank_mask = (1 << bank_nb) - 1

        row  = dfi_item.row  & row_mask
        col  = dfi_item.col  & col_mask
        bank = dfi_item.bank & bank_mask

        dram_addr  = (row  << (col_nb + bank_nb)) | \
                      (bank << (col_nb)) | col

        return dram_addr

    def final_phase(self):
        if not self.passed:
            self.logger.critical("{} reports a failure".format(type(self)))
            assert False


# =============================================================================

class WriteScoreboard(DFIScoreboard):
    """
    Scoreboard for DRAM write test. Analyzes Wishbone write requests and DFI
    activity. Predicts (computes) DRAM addresses and checks if data written
    through Wishbone matches data written to DRAM
    """

    def check_phase(self):

        total    = 0
        mismatch = 0

        while self.bus_port.can_get():

            # Get items
            got_bus, bus_item = self.bus_port.try_get()
            got_dfi, dfi_item = self.dfi_port.try_get()

            if not got_dfi:
                self.logger.critical("No DFI read/write for for DRAM command")
                self.passed = False
                continue

            # Discard if both items are not write
            if not isinstance(bus_item, BusWriteItem):
                continue
            if not isinstance(bus_item, BusRandomWriteItem):
                continue

            if not isinstance(dfi_item, DRAMWriteItem):
                continue

            # Check items
            check = True

            if bus_item.data.n_bits not in [32]:
                self.logger.critical("Unsupported bus data width {}",
                    bus_item.data.n_bits
                )
                check = False

            if dfi_item.data.n_bits not in [32, 64]:
                self.logger.critical("Unsupported DFI data width {}",
                    dfi_item.data.n_bits
                )
                check = False

            ratio = dfi_item.data.n_bits / bus_item.data.n_bits
            if ratio  not in [1.0, 2.0, 4.0]:
                self.logger.critical("Unsupported bus to DFI data ratio")
                check = False

            # Get data word being written
            if dfi_item.data.n_bits == 64:
                if dfi_item.mask == 0x0F:
                    word = 1
                elif dfi_item.mask == 0xF0:
                    word = 0
                else:
                    # TODO: Its not strictly invalid but shouldn't happen.
                    self.logger.critical(
                        "Invalid DFI data mask 0x{:02X}".format(
                            dfi_item.mask.integer
                        )
                    )
                    check = False

            elif dfi_item.data.n_bits == 32:
                if dfi_item.mask == 0x0:
                    word = 0
                else:
                    # TODO: Its not strictly invalid but shouldn't happen.
                    self.logger.critical(
                        "Invalid DFI data mask 0x{:01X}".format(
                            dfi_item.mask.integer
                        )
                    )
                    check = False

            else:
                # Shouldn't happen
                assert False

            # Failure
            if not check:
                self.passed = False
                continue

            # Build DRAM address
            dram_addr  = self.decode_dram_address(dfi_item) >> (3 - (int)(ratio - 1))
            dram_addr |= word
            dram_data  = (dfi_item.data >> (32 * word)) & 0xFFFFFFFF

            msg = "bus={:08X}:{:08X} vs. dfi={:08X}:{:08X}, bank={} row=0x{:04X} col=0x:{:04X} mask=0x{:02X}".format(
                bus_item.addr,
                int(bus_item.data),
                dram_addr,
                dram_data,
                dfi_item.bank,
                dfi_item.row,
                dfi_item.col,
                int(dfi_item.mask),
            )

            # Check
            total += 1
            if dram_addr == bus_item.addr and dram_data == int(bus_item.data):
                self.logger.debug(msg)
            else:
                mismatch += 1
                self.logger.error(msg)
                self.passed = False

        self.logger.info("{} / {} mismatches".format(mismatch, total))


# =============================================================================

class ReadScoreboard(DFIScoreboard):
    """
    Scoreboard for DRAM read test. Analyzes Wishbone read requests and DFI
    activity. Predicts (computes) DRAM addresses and checks if data read
    through Wishbone matches data read from DRAM.
    """

    def check_phase(self):

        total    = 0
        mismatch = 0

        while self.bus_port.can_get():

            # Get items
            got_bus, bus_item = self.bus_port.try_get()
            got_dfi, dfi_item = self.dfi_port.try_get()

            if not got_dfi:
                self.logger.critical("No DFI read/write for for DRAM command")
                self.passed = False
                continue

            # Discard if both items are not read
            if not isinstance(bus_item, BusReadItem):
                continue
            if not isinstance(bus_item, BusRandomReadItem):
                continue

            if not isinstance(dfi_item, DRAMReadItem):
                continue

            # Check items
            # FIXME: Support bus to DFI width ratio
            if bus_item.data.n_bits != dfi_item.data.n_bits:
                self.logger.critical("Bus data width must be equal to DFI data width")
                self.passed = False
                continue

            # Build DRAM address
            dram_addr = self.decode_dram_address(dfi_item) >> 3

            # Check
            msg = "bus={:08X}:{:08X} vs. dfi={:08X}:{:08X}, bank={} row=0x{:04X} col=0x:{:04X}".format(
                bus_item.addr,
                int(bus_item.data),
                dram_addr,
                int(dfi_item.data),
                dfi_item.bank,
                dfi_item.row,
                dfi_item.col
            )

            total += 1
            if dram_addr == bus_item.addr and int(dfi_item.data) == int(bus_item.data):
                self.logger.debug(msg)
            else:
                mismatch += 1
                self.logger.error(msg)
                self.passed = False

        self.logger.info("{} / {} mismatches".format(mismatch, total))

