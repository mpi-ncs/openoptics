# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# This software is licensed for non-commercial scientific research purposes only.
# License text: Creative Commons NC BY SA 4.0
#
# Tests for openoptics/Toolbox.py (BaseNetwork).
# Backend is replaced with FakeBackend so no Mininet/Docker is required.

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from helpers import FakeBackend
from openoptics.Toolbox import BaseNetwork


def _make_net(nb_node=4, nb_link=1, arch_mode="TO"):
    """Return a BaseNetwork backed by FakeBackend — no Mininet required."""
    backend = FakeBackend(nb_node=nb_node)
    with patch("openoptics.Toolbox.create_backend", return_value=backend):
        net = BaseNetwork(
            name="test_net",
            nb_node=nb_node,
            nb_link=nb_link,
            arch_mode=arch_mode,
            use_webserver=False,
        )
    return net, backend


# ---------------------------------------------------------------------------
# cal_node_port_to_ocs_port
# ---------------------------------------------------------------------------

class TestCalNodePortToOcsPort(unittest.TestCase):

    def setUp(self):
        self.net, _ = _make_net(nb_node=4)

    def test_first_node_first_port(self):
        self.assertEqual(self.net.cal_node_port_to_ocs_port(0, 0), 0)

    def test_formula_port_id_times_nb_node_plus_node_id(self):
        # ocs_port = port_id * nb_node + node_id
        nb_node = 4
        for node_id in range(nb_node):
            for port_id in range(2):
                expected = port_id * nb_node + node_id
                self.assertEqual(
                    self.net.cal_node_port_to_ocs_port(node_id, port_id), expected,
                    msg=f"node_id={node_id}, port_id={port_id}"
                )


# ---------------------------------------------------------------------------
# BaseNetwork.connect()
# ---------------------------------------------------------------------------

class TestConnect(unittest.TestCase):

    def setUp(self):
        self.net, _ = _make_net(nb_node=4, nb_link=2)

    def test_connect_two_nodes_succeeds(self):
        self.assertTrue(self.net.connect(0, 0, 1))

    def test_connected_edge_exists_in_slice_to_topo(self):
        self.net.connect(0, 0, 1, port1=0, port2=0)
        self.assertTrue(self.net.slice_to_topo[0].has_edge(0, 1))

    def test_bidirectional_by_default(self):
        self.net.connect(0, 0, 1, port1=0, port2=0)
        self.assertTrue(self.net.slice_to_topo[0].has_edge(0, 1))
        self.assertTrue(self.net.slice_to_topo[0].has_edge(1, 0))

    def test_unidirectional_connect(self):
        self.net.connect(0, 0, 1, port1=0, port2=0, unidirectional=True)
        self.assertTrue(self.net.slice_to_topo[0].has_edge(0, 1))
        self.assertFalse(self.net.slice_to_topo[0].has_edge(1, 0))

    def test_port_occupancy_blocks_reuse(self):
        # port 0 of node 0 is used → cannot connect again on same port
        self.net.connect(0, 0, 1, port1=0, port2=0)
        result = self.net.connect(0, 0, 2, port1=0, port2=0)
        self.assertFalse(result)

    def test_different_port_connects_again(self):
        self.net.connect(0, 0, 1, port1=0, port2=0)
        result = self.net.connect(0, 0, 2, port1=1, port2=1)
        self.assertTrue(result)

    def test_fills_missing_time_slices(self):
        self.net.connect(2, 0, 1)  # skip ts 0 and 1
        self.assertIn(0, self.net.slice_to_topo)
        self.assertIn(1, self.net.slice_to_topo)
        self.assertIn(2, self.net.slice_to_topo)

    def test_invalid_time_slice_raises(self):
        with self.assertRaises(ValueError):
            self.net.connect(-1, 0, 1)

    def test_invalid_node_raises(self):
        with self.assertRaises(ValueError):
            self.net.connect(0, 0, 99)  # node 99 doesn't exist

    def test_edge_stores_port_attributes(self):
        self.net.connect(0, 0, 1, port1=1, port2=0)
        edge_data = self.net.slice_to_topo[0][0][1]
        self.assertEqual(edge_data["port1"], 1)
        self.assertEqual(edge_data["port2"], 0)

    def test_multiple_time_slices_independent(self):
        self.net.connect(0, 0, 1, port1=0, port2=0)
        self.net.connect(1, 0, 2, port1=0, port2=0)
        self.assertFalse(self.net.slice_to_topo[0].has_edge(0, 2))
        self.assertFalse(self.net.slice_to_topo[1].has_edge(0, 1))


# ---------------------------------------------------------------------------
# BaseNetwork.disconnect()
# ---------------------------------------------------------------------------

class TestDisconnect(unittest.TestCase):

    def setUp(self):
        self.net, _ = _make_net(nb_node=4)
        self.net.connect(0, 0, 1, port1=0, port2=0)

    def test_disconnect_removes_edge(self):
        self.net.disconnect(0, 0, 1, port1=0, port2=0)
        self.assertFalse(self.net.slice_to_topo[0].has_edge(0, 1))

    def test_disconnect_bidirectional_removes_both_edges(self):
        self.net.disconnect(0, 0, 1, port1=0, port2=0)
        self.assertFalse(self.net.slice_to_topo[0].has_edge(0, 1))
        self.assertFalse(self.net.slice_to_topo[0].has_edge(1, 0))

    def test_disconnect_frees_port(self):
        self.net.disconnect(0, 0, 1, port1=0, port2=0)
        # Port 0 of node 0 is now free — can reconnect
        self.assertTrue(self.net.connect(0, 0, 2, port1=0, port2=0))

    def test_disconnect_nonexistent_edge_returns_false(self):
        result = self.net.disconnect(0, 0, 3, port1=0, port2=0)
        self.assertFalse(result)

    def test_disconnect_nonexistent_time_slice_returns_false(self):
        result = self.net.disconnect(99, 0, 1, port1=0, port2=0)
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# BaseNetwork.deploy_topo()
# ---------------------------------------------------------------------------

class TestDeployTopo(unittest.TestCase):

    def setUp(self):
        self.net, self.backend = _make_net(nb_node=4)

    def test_deploy_single_circuit(self):
        circuits = [(0, 0, 1, 0, 0)]
        result = self.net.deploy_topo(circuits)
        self.assertTrue(result)

    def test_deploy_creates_backend_nodes_on_first_call(self):
        circuits = [(0, 0, 1, 0, 0)]
        self.net.deploy_topo(circuits)
        self.assertTrue(self.backend.setup_called)

    def test_deploy_calls_clear_ocs_table(self):
        self.net.deploy_topo([(0, 0, 1, 0, 0)])
        ocs_clears = [name for sw, name in self.backend.cleared if sw == "ocs"]
        self.assertIn("MyIngress.ocs_schedule", ocs_clears)

    def test_deploy_loads_ocs_table(self):
        self.net.deploy_topo([(0, 0, 1, 0, 0)])
        ocs_loads = [sw for sw, _ in self.backend.loaded if sw == "ocs"]
        self.assertTrue(len(ocs_loads) > 0, "Expected at least one load_table call for ocs")

    def test_deploy_loads_tor_tables(self):
        self.net.deploy_topo([(0, 0, 1, 0, 0)])
        tor_loads = [sw for sw, _ in self.backend.loaded if sw.startswith("tor")]
        self.assertGreaterEqual(len(tor_loads), 2, "Expected load_table for each ToR")

    def test_deploy_second_call_does_not_re_setup_backend(self):
        self.net.deploy_topo([(0, 0, 1, 0, 0)])
        self.backend.setup_called = False  # Reset flag
        self.net.deploy_topo([], start_fresh=False)
        self.assertFalse(self.backend.setup_called)

    def test_deploy_start_fresh_clears_topology(self):
        self.net.deploy_topo([(0, 0, 1, 0, 0)])
        self.net.deploy_topo([(0, 0, 1, 0, 0)], start_fresh=True)
        # After fresh deploy we should still have the topology
        self.assertIn(0, self.net.slice_to_topo)

    def test_deploy_conflicting_circuit_returns_false(self):
        # Both circuits try to use port 0 of node 0
        circuits = [(0, 0, 1, 0, 0), (0, 0, 2, 0, 0)]
        result = self.net.deploy_topo(circuits)
        self.assertFalse(result)

    def test_empty_topology_raises(self):
        with self.assertRaises(Exception):
            self.net.deploy_topo([])  # No time slices → exception

    def test_nb_time_slices_updated(self):
        self.net.deploy_topo([(0, 0, 1, 0, 0), (1, 0, 1, 0, 0)])
        self.assertEqual(self.net.nb_time_slices, 2)


# ---------------------------------------------------------------------------
# BaseNetwork.deploy_routing() — command dispatch
# ---------------------------------------------------------------------------

class TestDeployRouting(unittest.TestCase):

    def setUp(self):
        from openoptics import OpticalTopo, OpticalRouting
        self.net, self.backend = _make_net(nb_node=4)
        circuits = OpticalTopo.round_robin(nb_node=4)
        self.net.deploy_topo(circuits)
        self.backend.loaded.clear()  # Reset after deploy_topo

        topo = self.net.get_topo()
        self.paths = OpticalRouting.routing_direct(topo)

    def test_deploy_routing_returns_true(self):
        result = self.net.deploy_routing(self.paths, routing_mode="Per-hop")
        self.assertTrue(result)

    def test_deploy_routing_loads_entries_for_all_nodes(self):
        self.net.deploy_routing(self.paths, routing_mode="Per-hop")
        loaded_nodes = {sw for sw, _ in self.backend.loaded}
        for i in range(4):
            self.assertIn(f"tor{i}", loaded_nodes)

    def test_deploy_routing_start_fresh_clears_tables(self):
        self.net.deploy_routing(self.paths, routing_mode="Per-hop", start_fresh=True)
        cleared_nodes = {sw for sw, _ in self.backend.cleared}
        for i in range(4):
            self.assertIn(f"tor{i}", cleared_nodes)


# ---------------------------------------------------------------------------
# BaseNetwork backend kwargs validation
# ---------------------------------------------------------------------------

class TestBackendKwargsValidation(unittest.TestCase):

    def _make_with_kwargs(self, backend, **kwargs):
        with patch("openoptics.Toolbox.create_backend", return_value=backend):
            return BaseNetwork(name="t", nb_node=2, use_webserver=False, **kwargs)

    def test_unknown_kwarg_raises_at_init(self):
        backend = FakeBackend(nb_node=2)  # accepted_kwargs() returns set()
        with self.assertRaises(ValueError):
            self._make_with_kwargs(backend, totally_unknown=99)

    def test_valid_kwarg_stored_in_backend_kwargs(self):
        class DelayBackend(FakeBackend):
            @classmethod
            def accepted_kwargs(cls):
                return {"link_delay_ms"}

        backend = DelayBackend(nb_node=2)
        net = self._make_with_kwargs(backend, link_delay_ms=10)
        self.assertEqual(net._backend_kwargs, {"link_delay_ms": 10})

    def test_no_kwargs_stores_empty_dict(self):
        backend = FakeBackend(nb_node=2)
        net = self._make_with_kwargs(backend)
        self.assertEqual(net._backend_kwargs, {})

    def test_error_message_names_the_unknown_kwarg(self):
        backend = FakeBackend(nb_node=2)
        with self.assertRaises(ValueError) as ctx:
            self._make_with_kwargs(backend, bad_param=1)
        self.assertIn("bad_param", str(ctx.exception))

    def test_backend_kwargs_forwarded_to_setup(self):
        """Kwargs stored in _backend_kwargs must be passed to backend.setup()."""
        class DelayBackend(FakeBackend):
            def __init__(self, nb_node):
                super().__init__(nb_node)
                self.setup_kwargs_received = {}

            @classmethod
            def accepted_kwargs(cls):
                return {"link_delay_ms"}

            def setup(self, *, link_delay_ms=0, **kw):
                super().setup(link_delay_ms=link_delay_ms, **kw)
                self.setup_kwargs_received["link_delay_ms"] = link_delay_ms

        backend = DelayBackend(nb_node=2)
        net = self._make_with_kwargs(backend, link_delay_ms=7)
        from openoptics import OpticalTopo
        net.deploy_topo(OpticalTopo.round_robin(nb_node=2))
        self.assertEqual(backend.setup_kwargs_received.get("link_delay_ms"), 7)


if __name__ == "__main__":
    unittest.main()
