# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# This software is licensed for non-commercial scientific research purposes only.
# License text: Creative Commons NC BY SA 4.0
#
# Tests for openoptics/backends/base.py and openoptics/backends/__init__.py

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from openoptics.backends.base import BackendBase, SwitchHandle

try:
    import mininet  # noqa: F401
    HAS_MININET = True
except ImportError:
    HAS_MININET = False


# ---------------------------------------------------------------------------
# Minimal concrete backend used across tests
# ---------------------------------------------------------------------------

class _ConcreteBackend(BackendBase):
    """Minimal implementation to verify the interface."""

    def setup(self, *, nb_node, nb_host_per_tor, nb_link, nb_time_slices,
              time_slice_duration_ms, guardband_ms,
              tor_host_port, host_tor_port, tor_ocs_ports,
              calendar_queue_mode, **backend_kwargs):
        pass

    def get_switch(self, name):
        return SwitchHandle(name, 9090)

    def switch_exists(self, name):
        return True

    def get_tor_switches(self):
        return []

    def get_ip_to_tor(self):
        return {}

    def load_table(self, switch_name, table_commands, **kwargs):
        return True

    def clear_table(self, switch_name, table_name, **kwargs):
        pass

    def stop(self):
        pass

    def cleanup(self):
        pass


# ---------------------------------------------------------------------------
# SwitchHandle
# ---------------------------------------------------------------------------

class TestSwitchHandle(unittest.TestCase):

    def test_attributes_stored(self):
        sw = SwitchHandle("tor0", 9091)
        self.assertEqual(sw.name, "tor0")
        self.assertEqual(sw.thrift_port, 9091)

    def test_multiple_instances_independent(self):
        a = SwitchHandle("ocs", 9090)
        b = SwitchHandle("tor0", 9091)
        self.assertNotEqual(a.name, b.name)
        self.assertNotEqual(a.thrift_port, b.thrift_port)


# ---------------------------------------------------------------------------
# BackendBase — abstract contract
# ---------------------------------------------------------------------------

class TestBackendBaseAbstract(unittest.TestCase):

    def test_cannot_instantiate_directly(self):
        with self.assertRaises(TypeError):
            BackendBase()

    def test_concrete_subclass_can_be_instantiated(self):
        backend = _ConcreteBackend()
        self.assertIsInstance(backend, BackendBase)

    def test_default_get_cli_commands_returns_empty_dict(self):
        backend = _ConcreteBackend()
        self.assertEqual(backend.get_cli_commands(), {})

    def test_default_handler_returns_false(self):
        backend = _ConcreteBackend()
        self.assertFalse(backend.default_handler("h0 ping h1"))

    def test_partial_subclass_cannot_be_instantiated(self):
        """A subclass that skips an abstract method must not instantiate."""
        class IncompleteBackend(BackendBase):
            def setup(self, *, nb_node, nb_host_per_tor, nb_link, nb_time_slices,
                      time_slice_duration_ms, guardband_ms,
                      tor_host_port, host_tor_port, tor_ocs_ports,
                      calendar_queue_mode, **backend_kwargs): pass
            def get_switch(self, name): pass
            def switch_exists(self, name): pass
            def get_tor_switches(self): pass
            def get_ip_to_tor(self): pass
            def load_table(self, *a, **kw): pass
            def clear_table(self, *a, **kw): pass
            # Missing stop() and cleanup()

        with self.assertRaises(TypeError):
            IncompleteBackend()


# ---------------------------------------------------------------------------
# create_backend factory
# ---------------------------------------------------------------------------

class TestCreateBackend(unittest.TestCase):

    def test_unknown_backend_raises_value_error(self):
        from openoptics.backends import create_backend
        with self.assertRaises(ValueError, msg="Should raise for unknown backend name"):
            create_backend("NonExistentBackend")

    def test_empty_string_raises_value_error(self):
        from openoptics.backends import create_backend
        with self.assertRaises(ValueError):
            create_backend("")


# ---------------------------------------------------------------------------
# accepted_kwargs — BackendBase interface only (no networkx dependency)
# ---------------------------------------------------------------------------

class TestAcceptedKwargs(unittest.TestCase):

    def test_default_accepted_kwargs_is_empty(self):
        backend = _ConcreteBackend()
        self.assertEqual(type(backend).accepted_kwargs(), set())

    def test_subclass_can_declare_kwargs(self):
        class BackendWithDelay(_ConcreteBackend):
            @classmethod
            def accepted_kwargs(cls):
                return {"link_delay_ms"}

        self.assertIn("link_delay_ms", BackendWithDelay.accepted_kwargs())


# ---------------------------------------------------------------------------
# MininetBackend — link bandwidth forwarded to addLink()
# ---------------------------------------------------------------------------

@unittest.skipUnless(HAS_MININET, "mininet not installed")
class TestMininetBackendLinkBandwidth(unittest.TestCase):
    """Verify ocs_tor_link_bw and tor_host_link_bw reach Mininet addLink()."""

    def _run_setup(self, ocs_tor_link_bw=1000, tor_host_link_bw=1000):
        from unittest.mock import MagicMock, patch, call
        from openoptics.backends.mininet.backend import MininetBackend

        mock_topo = MagicMock()
        mock_topo.addSwitch.return_value = "switch"
        mock_topo.addHost.return_value = "host"

        mock_net = MagicMock()
        mock_net.__iter__ = MagicMock(return_value=iter([]))

        with patch("openoptics.backends.mininet.backend.Topo", return_value=mock_topo), \
             patch("openoptics.backends.mininet.backend.Mininet", return_value=mock_net), \
             patch("os.system"):
            backend = MininetBackend()
            backend.setup(
                nb_node=2,
                nb_host_per_tor=1,
                nb_link=1,
                nb_time_slices=1,
                time_slice_duration_ms=128,
                guardband_ms=25,
                tor_host_port=1,
                host_tor_port=0,
                tor_ocs_ports=[0],
                calendar_queue_mode=0,
                ocs_tor_link_bw=ocs_tor_link_bw,
                tor_host_link_bw=tor_host_link_bw,
            )

        return mock_topo.addLink.call_args_list

    def test_ocs_tor_link_bw_passed_to_addlink(self):
        calls = self._run_setup(ocs_tor_link_bw=5000)
        ocs_tor_calls = [c for c in calls if c.kwargs.get("bw") == 5000]
        self.assertTrue(len(ocs_tor_calls) > 0, "Expected addLink call with bw=5000 for OCS-ToR link")

    def test_tor_host_link_bw_passed_to_addlink(self):
        calls = self._run_setup(tor_host_link_bw=2000)
        host_tor_calls = [c for c in calls if c.kwargs.get("bw") == 2000]
        self.assertTrue(len(host_tor_calls) > 0, "Expected addLink call with bw=2000 for host-ToR link")

    def test_default_bw_is_1000_for_both(self):
        calls = self._run_setup()
        bw_values = [c.kwargs.get("bw") for c in calls if "bw" in c.kwargs]
        self.assertTrue(all(v == 1000 for v in bw_values), f"Expected all bw=1000, got {bw_values}")


if __name__ == "__main__":
    unittest.main()
