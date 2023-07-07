# DRAM Controller

A DRAM controller with DFI interface based on LiteDRAM

## Building

Clone submodules
```bash
git submodule update --init --recursive
```

Install prerequisities (preferrably in a Python virtualenv). **Use Python3 < 11.0 as version 11 causes some problems with Migen.**
```bash
pip install -r requirements.txt
```

Generate the core using the example configuration:
```bash
./gen.py standalone-dfi.yml
```

Build files should be written to the `build` directory by default.
