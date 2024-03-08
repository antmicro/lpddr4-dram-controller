// Copyright (c) 2024 Antmicro <www.antmicro.com>
// SPDX-License-Identifier: Apache-2.0

module ander(
    input logic clk,
    input logic rst,
    input logic [31:0] d1,
    input logic [31:0] d2,
    output logic [31:0] q
);

logic [31:0] internal;
assign internal = d1 & d2;

always_ff@(posedge clk or posedge rst)
begin: proc_registers
    if (rst)
        q <= '0;
    else
        q <= internal;
end

endmodule
