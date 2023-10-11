# DRAM Controller

Copyright (c) 2023 [Antmicro](https://antmicro.com/)

## Introduction

This project contains a DRAM controller with DFI interface based on LiteDRAM.

## Prerequisites

Clone submodules:
```bash
git submodule update --init --recursive
```

Install prerequisities (preferrably in a Python virtualenv). **Use Python3 < 11.0 as version 11 causes some problems with Migen.**
```bash
pip install -r requirements.txt
```

If you want to enable testing capabilities, you will also need a [Verilator](https://github.com/verilator/verilator) simulator.

## Building

Generate the core using the example configuration:
```bash
make verilog
```

Build files will be written to the `build` directory.
Custom DFI configuration file can be provided by passing `CONFIG` flag to the Make build flow.

## Testing

With all prerequisites satisfied, it should be sufficient to run `make tests` to execute all available tests.
