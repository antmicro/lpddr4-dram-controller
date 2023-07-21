# Copyright (c) 2023
# SPDX-License-Identifier: Apache-2.0

"""
A module responsible for loading register definitions from a CSV file.
"""

from collections import namedtuple

# =============================================================================

CSR = namedtuple("CSR", "name address width access")

def load_csrs(csr_csv):
    
    with open(csr_csv, "r") as fp:
        lines = fp.readlines()

    csrs = dict()

    for line in lines:
        line = line.strip()

        if not line or line.startswith("#"):
            continue

        fields = line.split(",")

        if fields[0] == "csr_register":
            name    = fields[1]
            address = int(fields[2], 0)
            width   = int(fields[3])
            access  = fields[4]

            csrs[name] = CSR(name, address, width, access)

    return csrs
