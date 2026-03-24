# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# This software is licensed for non-commercial scientific research purposes only.
# License text: Creative Commons NC BY SA 4.0
#
# Tests for openoptics/OpticalRouting.py

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import networkx as nx
from openoptics import OpticalTopo, OpticalRouting
from openoptics.TimeFlowTable import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_slice_to_topo(nb_node, circuits):
    """Build a slice_to_topo dict from a list of circuits without BaseNetwork."""
    slice_to_topo = {}
    for ts, n1, n2, p1, p2 in circuits:
        if ts not in slice_to_topo:
            g = nx.DiGraph()
            g.add_nodes_from(range(nb_node))
            slice_to_topo[ts] = g
        slice_to_topo[ts].add_edge(n1, n2, port1=p1, port2=p2)
        slice_to_topo[ts].add_edge(n2, n1, port1=p2, port2=p1)
    return slice_to_topo


def _rr_topo(nb_node=4):
    circuits = OpticalTopo.round_robin(nb_node=nb_node)
    return _build_slice_to_topo(nb_node, circuits)


# ---------------------------------------------------------------------------
# find_send_port
# ---------------------------------------------------------------------------

class TestFindSendPort(unittest.TestCase):

    def setUp(self):
        g = nx.DiGraph()
        g.add_edge(0, 1, port1=2)
        g.add_edge(1, 0, port1=3)
        self.topo = g

    def test_existing_edge_returns_port(self):
        self.assertEqual(OpticalRouting.find_send_port(self.topo, 0, 1), 2)

    def test_reverse_edge_returns_correct_port(self):
        self.assertEqual(OpticalRouting.find_send_port(self.topo, 1, 0), 3)

    def test_missing_edge_returns_none(self):
        self.assertIsNone(OpticalRouting.find_send_port(self.topo, 0, 5))


# ---------------------------------------------------------------------------
# find_direct_path
# ---------------------------------------------------------------------------

class TestFindDirectPath(unittest.TestCase):

    def setUp(self):
        self.slice_to_topo = _rr_topo(nb_node=4)

    def test_same_src_dst_returns_empty(self):
        paths = OpticalRouting.find_direct_path(self.slice_to_topo, 0, 0)
        self.assertEqual(paths, [])

    def test_returns_path_objects(self):
        paths = OpticalRouting.find_direct_path(self.slice_to_topo, 0, 1)
        self.assertGreater(len(paths), 0)
        for p in paths:
            self.assertIsInstance(p, Path)

    def test_all_paths_have_correct_src_dst(self):
        paths = OpticalRouting.find_direct_path(self.slice_to_topo, 0, 3)
        for p in paths:
            self.assertEqual(p.src, 0)
            self.assertEqual(p.dst, 3)

    def test_no_direct_link_returns_empty(self):
        g = nx.DiGraph()
        g.add_nodes_from([0, 1, 2])
        g.add_edge(0, 2, port1=0)  # only 0→2, no 0→1
        paths = OpticalRouting.find_direct_path({0: g}, 0, 1)
        self.assertEqual(paths, [])

    def test_paths_cover_all_arrival_time_slices(self):
        """For a fully-connected round-robin, direct paths should cover every ts."""
        paths = OpticalRouting.find_direct_path(self.slice_to_topo, 0, 1)
        arrival_ts_set = {p.arrival_ts for p in paths}
        all_ts = set(self.slice_to_topo.keys())
        self.assertEqual(arrival_ts_set, all_ts)

    def test_each_path_has_exactly_one_step(self):
        paths = OpticalRouting.find_direct_path(self.slice_to_topo, 0, 1)
        for p in paths:
            self.assertEqual(len(p.steps), 1)


# ---------------------------------------------------------------------------
# routing_direct
# ---------------------------------------------------------------------------

class TestRoutingDirect(unittest.TestCase):

    def setUp(self):
        self.nb_node = 4
        self.slice_to_topo = _rr_topo(self.nb_node)

    def test_returns_list_of_paths(self):
        paths = OpticalRouting.routing_direct(self.slice_to_topo)
        self.assertIsInstance(paths, list)
        self.assertGreater(len(paths), 0)

    def test_all_node_pairs_covered(self):
        paths = OpticalRouting.routing_direct(self.slice_to_topo)
        pairs_covered = {(p.src, p.dst) for p in paths}
        for src in range(self.nb_node):
            for dst in range(self.nb_node):
                if src != dst:
                    self.assertIn((src, dst), pairs_covered,
                                  msg=f"Missing path for {src} → {dst}")

    def test_no_self_loops(self):
        paths = OpticalRouting.routing_direct(self.slice_to_topo)
        for p in paths:
            self.assertNotEqual(p.src, p.dst)

    def test_each_path_single_step(self):
        paths = OpticalRouting.routing_direct(self.slice_to_topo)
        for p in paths:
            self.assertEqual(len(p.steps), 1)


# ---------------------------------------------------------------------------
# routing_direct_ta
# ---------------------------------------------------------------------------

class TestRoutingDirectTa(unittest.TestCase):

    def test_raises_for_multiple_time_slices(self):
        slice_to_topo = _rr_topo(nb_node=4)  # has 3 slices
        with self.assertRaises(AssertionError):
            OpticalRouting.routing_direct_ta(slice_to_topo)

    def test_single_slice_returns_n_squared_minus_n_paths(self):
        nb_node = 4
        g = nx.DiGraph()
        g.add_nodes_from(range(nb_node))
        for i in range(nb_node):
            for j in range(nb_node):
                if i != j:
                    g.add_edge(i, j, port1=0)
        paths = OpticalRouting.routing_direct_ta({0: g})
        self.assertEqual(len(paths), nb_node * (nb_node - 1))

    def test_all_paths_use_arrival_ts_0(self):
        nb_node = 3
        g = nx.DiGraph()
        g.add_nodes_from(range(nb_node))
        for i in range(nb_node):
            for j in range(nb_node):
                if i != j:
                    g.add_edge(i, j, port1=0)
        paths = OpticalRouting.routing_direct_ta({0: g})
        for p in paths:
            self.assertEqual(p.arrival_ts, 0)


# ---------------------------------------------------------------------------
# routing_vlb
# ---------------------------------------------------------------------------

class TestRoutingVlb(unittest.TestCase):

    def setUp(self):
        self.nb_node = 4
        self.slice_to_topo = _rr_topo(self.nb_node)
        # VLB uses one port per time slice for indirect hops
        self.tor_to_ocs_port = [0, 1, 2]

    def test_returns_paths_for_all_pairs_and_slices(self):
        paths = OpticalRouting.routing_vlb(self.slice_to_topo, self.tor_to_ocs_port)
        nb_ts = len(self.slice_to_topo)
        nb_pairs = self.nb_node * (self.nb_node - 1)
        self.assertEqual(len(paths), nb_pairs * nb_ts)

    def test_direct_paths_have_one_step(self):
        paths = OpticalRouting.routing_vlb(self.slice_to_topo, self.tor_to_ocs_port)
        for p in paths:
            if len(p.steps) == 1:
                # Direct path: step is port-based
                self.assertEqual(p.steps[0].step_type, "port")


# ---------------------------------------------------------------------------
# remove_suboptimal_paths
# ---------------------------------------------------------------------------

class TestRemoveSuboptimalPaths(unittest.TestCase):

    def _path(self, src, dst, arrival_ts, send_ts):
        from openoptics.TimeFlowTable import Step
        step = Step(cur_node=src, step_type="port", send_port=0, send_ts=send_ts)
        return Path(src=src, arrival_ts=arrival_ts, dst=dst, steps=[step])

    def test_keeps_earliest_send_ts_per_arrival_ts(self):
        p1 = self._path(0, 1, arrival_ts=0, send_ts=2)
        p2 = self._path(0, 1, arrival_ts=0, send_ts=1)  # shorter duration from ts 0
        result = OpticalRouting.remove_suboptimal_paths([p1, p2], nb_ts=4)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].steps[-1].send_ts, 1)

    def test_different_arrival_ts_kept_separately(self):
        p1 = self._path(0, 1, arrival_ts=0, send_ts=0)
        p2 = self._path(0, 1, arrival_ts=1, send_ts=1)
        result = OpticalRouting.remove_suboptimal_paths([p1, p2], nb_ts=4)
        self.assertEqual(len(result), 2)


# ---------------------------------------------------------------------------
# extend_paths_to_all_time_slice
# ---------------------------------------------------------------------------

class TestExtendPathsToAllTimeSlice(unittest.TestCase):

    def _path(self, src, dst, arrival_ts):
        from openoptics.TimeFlowTable import Step
        step = Step(cur_node=src, step_type="port", send_port=0, send_ts=arrival_ts)
        return Path(src=src, arrival_ts=arrival_ts, dst=dst, steps=[step])

    def test_fills_missing_arrival_ts(self):
        # Only paths at ts 0 and 2; ts 1 and 3 must be filled
        paths = [self._path(0, 1, 0), self._path(0, 1, 2)]
        result = OpticalRouting.extend_paths_to_all_time_slice(paths, nb_ts=4)
        arrival_ts_set = {p.arrival_ts for p in result}
        self.assertEqual(arrival_ts_set, {0, 1, 2, 3})

    def test_result_length_equals_nb_ts(self):
        paths = [self._path(0, 1, 1)]
        result = OpticalRouting.extend_paths_to_all_time_slice(paths, nb_ts=4)
        self.assertEqual(len(result), 4)

    def test_empty_paths_raises(self):
        with self.assertRaises(AssertionError):
            OpticalRouting.extend_paths_to_all_time_slice([], nb_ts=4)


if __name__ == "__main__":
    unittest.main()
