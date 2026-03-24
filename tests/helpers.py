# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# This software is licensed for non-commercial scientific research purposes only.
# License text: Creative Commons NC BY SA 4.0
#
# Shared test helpers — not a test file (no test_* prefix).

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from openoptics.backends.base import BackendBase, SwitchHandle


class FakeBackend(BackendBase):
    """In-memory backend for unit tests — no Mininet required.

    Records ``load_table`` and ``clear_table`` calls so tests can assert
    on what was written to the P4 switches.
    """

    def __init__(self, nb_node=4):
        self._nb_node = nb_node
        self._ip_to_tor = {f"10.0.{i}.1": i for i in range(nb_node)}
        self._tor_handles = [
            SwitchHandle(f"tor{i}", 9091 + i) for i in range(nb_node)
        ]
        self._switches = {sw.name: sw for sw in self._tor_handles}
        self._switches["ocs"] = SwitchHandle("ocs", 9090)

        # Call records for assertions
        self.loaded: list = []   # [(switch_name, table_commands), ...]
        self.cleared: list = []  # [(switch_name, table_name), ...]
        self.setup_called = False
        self.stop_called = False

    # --- BackendBase abstract methods ---

    def setup(self, *, nb_node, nb_host_per_tor, nb_link, nb_time_slices,
              time_slice_duration_ms, guardband_ms,
              tor_host_port, host_tor_port, tor_ocs_ports,
              calendar_queue_mode, **backend_kwargs) -> None:
        self.setup_called = True

    def get_switch(self, name: str) -> SwitchHandle:
        return self._switches[name]

    def switch_exists(self, name: str) -> bool:
        return name in self._switches

    def get_tor_switches(self) -> list:
        return list(self._tor_handles)

    def get_ip_to_tor(self) -> dict:
        return dict(self._ip_to_tor)

    def load_table(self, switch_name, table_commands, **kwargs) -> bool:
        self.loaded.append((switch_name, table_commands))
        return True

    def clear_table(self, switch_name, table_name, **kwargs) -> None:
        self.cleared.append((switch_name, table_name))

    def stop(self) -> None:
        self.stop_called = True

    def cleanup(self) -> None:
        pass
