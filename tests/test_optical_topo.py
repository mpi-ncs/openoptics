# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# This software is licensed for non-commercial scientific research purposes only.
# License text: Creative Commons NC BY SA 4.0
#
# Tests for openoptics/OpticalTopo.py

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from openoptics import OpticalTopo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_nodes_in_circuits(circuits, nb_node):
    """Return the set of nodes that appear in any circuit."""
    nodes = set()
    for ts, n1, n2, p1, p2 in circuits:
        nodes.add(n1)
        nodes.add(n2)
    return nodes


def _connections_at_ts(circuits, ts):
    """Return {node: connected_node} for all circuits at a given time slice."""
    conn = {}
    for c_ts, n1, n2, p1, p2 in circuits:
        if c_ts == ts:
            conn[n1] = n2
            conn[n2] = n1
    return conn


# ---------------------------------------------------------------------------
# get_nb_time_slice_from_circuits / get_nb_links_from_circuits
# ---------------------------------------------------------------------------

class TestHelperFunctions(unittest.TestCase):

    def test_nb_time_slices_single(self):
        circuits = [[0, 0, 1, 0, 0]]
        self.assertEqual(OpticalTopo.get_nb_time_slice_from_circuits(circuits), 1)

    def test_nb_time_slices_multiple(self):
        circuits = [[0, 0, 1, 0, 0], [2, 1, 2, 0, 0]]  # ts 0 and 2
        self.assertEqual(OpticalTopo.get_nb_time_slice_from_circuits(circuits), 3)

    def test_nb_links_single_port(self):
        circuits = [[0, 0, 1, 0, 0], [1, 0, 2, 0, 0]]
        self.assertEqual(OpticalTopo.get_nb_links_from_circuits(circuits), 1)

    def test_nb_links_multiple_ports(self):
        circuits = [[0, 0, 1, 0, 0], [0, 0, 2, 1, 1]]  # ports 0 and 1
        self.assertEqual(OpticalTopo.get_nb_links_from_circuits(circuits), 2)


# ---------------------------------------------------------------------------
# round_robin
# ---------------------------------------------------------------------------

class TestRoundRobin(unittest.TestCase):

    def test_4_nodes_produces_3_time_slices(self):
        circuits = OpticalTopo.round_robin(nb_node=4)
        ts_set = {c[0] for c in circuits}
        self.assertEqual(ts_set, {0, 1, 2})

    def test_4_nodes_each_node_connected_every_other_node_over_all_slices(self):
        circuits = OpticalTopo.round_robin(nb_node=4)
        # Over all time slices every node must meet every other node exactly once
        connections = {n: set() for n in range(4)}
        for ts, n1, n2, p1, p2 in circuits:
            connections[n1].add(n2)
            connections[n2].add(n1)
        for node in range(4):
            self.assertEqual(connections[node], set(range(4)) - {node})

    def test_2_nodes_single_time_slice(self):
        circuits = OpticalTopo.round_robin(nb_node=2)
        self.assertEqual(len(circuits), 1)
        self.assertEqual(circuits[0][0], 0)  # time slice 0

    def test_odd_number_of_nodes_uses_dummy(self):
        # 3 nodes → padded to 4, dummy node (-1) omitted from circuits
        circuits = OpticalTopo.round_robin(nb_node=3)
        for ts, n1, n2, p1, p2 in circuits:
            self.assertNotEqual(n1, -1)
            self.assertNotEqual(n2, -1)

    def test_custom_nodes_list(self):
        circuits = OpticalTopo.round_robin(nodes=[10, 20, 30, 40])
        nodes = _all_nodes_in_circuits(circuits, 4)
        self.assertEqual(nodes, {10, 20, 30, 40})

    def test_start_time_slice_offset(self):
        circuits = OpticalTopo.round_robin(nb_node=4, start_time_slice=5)
        ts_set = {c[0] for c in circuits}
        self.assertGreaterEqual(min(ts_set), 5)

    def test_self_loop_adds_extra_time_slice(self):
        circuits_no_loop = OpticalTopo.round_robin(nb_node=4, self_loop=False)
        circuits_loop = OpticalTopo.round_robin(nb_node=4, self_loop=True)
        ts_set_no_loop = {c[0] for c in circuits_no_loop}
        ts_set_loop = {c[0] for c in circuits_loop}
        self.assertGreater(len(ts_set_loop), len(ts_set_no_loop))

    def test_custom_port_assignment(self):
        circuits = OpticalTopo.round_robin(nb_node=4, port1=2, port2=3)
        for ts, n1, n2, p1, p2 in circuits:
            self.assertEqual(p1, 2)
            self.assertEqual(p2, 3)


# ---------------------------------------------------------------------------
# opera
# ---------------------------------------------------------------------------

class TestOpera(unittest.TestCase):

    def test_4_nodes_2_links_structure(self):
        circuits = OpticalTopo.opera(nb_node=4, nb_link=2)
        self.assertIsInstance(circuits, list)
        self.assertGreater(len(circuits), 0)

    def test_all_4_nodes_present(self):
        circuits = OpticalTopo.opera(nb_node=4, nb_link=2)
        nodes = _all_nodes_in_circuits(circuits, 4)
        # Dummy self-loop nodes may appear; real nodes must be present
        self.assertTrue({0, 1, 2, 3}.issubset(nodes))

    def test_port_ids_within_range(self):
        nb_link = 2
        circuits = OpticalTopo.opera(nb_node=4, nb_link=nb_link)
        for ts, n1, n2, p1, p2 in circuits:
            self.assertLess(p1, nb_link, msg=f"port1={p1} out of range")
            self.assertLess(p2, nb_link, msg=f"port2={p2} out of range")

    def test_disable_last_ts(self):
        circuits_full = OpticalTopo.opera(nb_node=4, nb_link=2)
        circuits_trimmed = OpticalTopo.opera(nb_node=4, nb_link=2, disable_last_ts=True)
        ts_full = {c[0] for c in circuits_full}
        ts_trimmed = {c[0] for c in circuits_trimmed}
        self.assertLessEqual(len(ts_trimmed), len(ts_full))


# ---------------------------------------------------------------------------
# port_offset
# ---------------------------------------------------------------------------

class TestPortOffset(unittest.TestCase):

    def test_single_link_identity(self):
        """With one link (port 0 only), offset is a no-op in structure."""
        circuits = [[0, 0, 1, 0, 0], [1, 0, 2, 0, 0]]
        result = OpticalTopo.port_offset(circuits)
        # Each original circuit should expand to nb_links entries
        self.assertEqual(len(result), len(circuits) * 1)

    def test_two_links_doubles_entries(self):
        circuits = [[0, 0, 1, 0, 0], [0, 2, 3, 1, 1]]
        result = OpticalTopo.port_offset(circuits)
        self.assertEqual(len(result), len(circuits) * 2)

    def test_port_mismatch_raises(self):
        circuits = [[0, 0, 1, 0, 1]]  # port1 != port2
        with self.assertRaises(AssertionError):
            OpticalTopo.port_offset(circuits)



# ---------------------------------------------------------------------------
# static_topo
# ---------------------------------------------------------------------------

class TestStaticTopo(unittest.TestCase):

    def test_regular_graph_degree(self):
        nb_node, nb_link = 6, 2
        circuits = OpticalTopo.static_topo(nb_node=nb_node, nb_link=nb_link)
        degree = {n: 0 for n in range(nb_node)}
        for ts, n1, n2, p1, p2 in circuits:
            degree[n1] += 1
            degree[n2] += 1
        for node, deg in degree.items():
            self.assertEqual(deg, nb_link, msg=f"node {node} has degree {deg}")

    def test_single_link_edges_count(self):
        nb_node = 4
        circuits = OpticalTopo.static_topo(nb_node=nb_node, nb_link=1)
        # A 1-regular graph on 4 nodes has 2 edges
        self.assertEqual(len(circuits), nb_node // 2)

    def test_all_in_time_slice_0(self):
        circuits = OpticalTopo.static_topo(nb_node=4, nb_link=1)
        for ts, *_ in circuits:
            self.assertEqual(ts, 0)


# ---------------------------------------------------------------------------
# bipartite_matching
# ---------------------------------------------------------------------------

class TestBipartiteMatching(unittest.TestCase):

    def test_returns_circuits_for_nonzero_traffic(self):
        traffic = {(0, 1): 10, (2, 3): 5}
        circuits = OpticalTopo.bipartite_matching(nb_node=4, nb_link=1, traffic_matrix=traffic)
        self.assertIsInstance(circuits, list)
        self.assertGreater(len(circuits), 0)

    def test_returns_prev_circuits_for_zero_traffic(self):
        traffic = {(0, 1): 0, (1, 0): 0}
        prev = [[0, 0, 1, 0, 0]]
        circuits = OpticalTopo.bipartite_matching(
            nb_node=4, nb_link=1, traffic_matrix=traffic, prev_circuits=prev
        )
        self.assertEqual(circuits, prev)

    def test_raises_if_nb_link_not_1(self):
        with self.assertRaises(AssertionError):
            OpticalTopo.bipartite_matching(nb_node=4, nb_link=2, traffic_matrix={})


if __name__ == "__main__":
    unittest.main()
