#!/bin/bash
set -ex

echo "ROOT_DIR=${PWD}" >> $GITHUB_ENV

install_klayout() {
    if ! command -v klayout > /dev/null; then
        wget ${KLAYOUT_URL}${KLAYOUT_DEB}
        sudo dpkg -i ${KLAYOUT_DEB}
        rm ${KLAYOUT_DEB}
    fi
}

install_yosys() {
    if ! command -v yosys > /dev/null; then
        wget ${YOSYS_URL}${YOSYS_TGZ}
        tar xf ${YOSYS_TGZ}
        OSS_BIN=${PWD}/oss-cad-suite/bin
        echo "${YOSYS_BIN}" >> $GITHUB_PATH
        echo "YOSYS_CMD=${OSS_BIN}/yosys" >> $GITHUB_ENV
        rm ${YOSYS_TGZ}
    fi
}

install_openroad() {
    if ! command -v openroad > /dev/null; then
        wget ${OPENROAD_URL}${OPENROAD_DEB}
        sudo dpkg -i ${OPENROAD_DEB}
        echo "OPENROAD_EXE=$(command -v openroad)" >> $GITHUB_ENV
        rm ${OPENROAD_DEB}
    fi
}
