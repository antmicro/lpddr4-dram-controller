from pyuvm import *

# =============================================================================

class DFIScoreboard(uvm_component):

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
