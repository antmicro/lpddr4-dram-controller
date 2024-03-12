# Copyright (c) 2023-2024 Antmicro <www.antmicro.com>
# SPDX-License-Identifier: Apache-2.0

import pyuvm

from testbench import BaseTest

# =============================================================================

@pyuvm.test()
class TestInit(BaseTest):
    """
    Just runs the base test which initializes the controller
    """

    async def run(self):
        pass
