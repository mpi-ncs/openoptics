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


if __name__ == "__main__":
    unittest.main()
