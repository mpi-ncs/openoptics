# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# Author: Yiming Lei (ylei@mpi-inf.mpg.de)
#
# License text: Creative Commons NC BY SA 4.0
# https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en

"""ns-3 backend skeleton.

Stub implementation. The backend expects a user-installed ns-3 at the path given
by the ``NS3_DIR`` environment variable. Our C++ modules under ``src/`` are
shipped as package data and compiled on first use against the local ns-3 build.

This file currently only declares the class so ``create_backend("ns3")`` can
load without ImportError and produce an actionable NotImplementedError.
"""
from __future__ import annotations

import os
from pathlib import Path

from openoptics.backends.base import BackendBase


class Ns3Backend(BackendBase):
    supports_device_manager = False

    def __init__(self) -> None:
        self._ns3_dir = os.environ.get("NS3_DIR")
        if not self._ns3_dir:
            raise RuntimeError(
                "ns-3 backend requires the NS3_DIR environment variable to point "
                "at a built ns-3 source tree."
            )
        self._src_dir = Path(__file__).resolve().parent / "src"

    def _not_implemented(self, name: str):
        raise NotImplementedError(
            f"Ns3Backend.{name} is not yet implemented. "
            "See https://github.com/mpi-ncs/openoptics for status."
        )

    def setup(self, *args, **kwargs):           self._not_implemented("setup")
    def get_switch(self, name):                 self._not_implemented("get_switch")
    def switch_exists(self, name):              self._not_implemented("switch_exists")
    def get_tor_switches(self):                 self._not_implemented("get_tor_switches")
    def get_ip_to_tor(self):                    self._not_implemented("get_ip_to_tor")
    def load_table(self, *args, **kwargs):      self._not_implemented("load_table")
    def clear_table(self, *args, **kwargs):     self._not_implemented("clear_table")
    def stop(self):                             self._not_implemented("stop")
    def cleanup(self):                          self._not_implemented("cleanup")
