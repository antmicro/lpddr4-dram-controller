#!/bin/bash


export FLOW_DIR=third_party/OpenROAD-flow-scripts/flow/
export PDK=asap7
export DESIGN=ander
export ACTIVITY_LIST="0.0 0.5 1.0"

sta -exit opensta/power.tcl
