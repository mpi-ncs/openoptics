# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# This software is licensed for non-commercial scientific research purposes only.
# License text: Creative Commons NC BY SA 4.0
#
# Tests for openoptics/utils.py

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import networkx as nx
from openoptics import utils
from openoptics.TimeFlowTable import Path, Step, TimeFlowEntry, TimeFlowHop
from openoptics.backends.base import TableEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _one_slice_topo(edges):
    """Build a single-slice slice_to_topo with the given directed edges.

    edges: list of (src, dst, port1) tuples
    """
    g = nx.DiGraph()
    for src, dst, port in edges:
        g.add_edge(src, dst, port1=port)
    return {0: g}


def _simple_path(src=0, dst=1, arrival_ts=0, send_port=0, send_ts=0):
    step = Step(cur_node=src, step_type="port", send_port=send_port, send_ts=send_ts, send_node=dst)
    return Path(src=src, arrival_ts=arrival_ts, dst=dst, steps=[step])


# ---------------------------------------------------------------------------
# gen_ocs_commands
# ---------------------------------------------------------------------------

class TestGenOcsCommands(unittest.TestCase):

    def test_empty_entries_still_has_default(self):
        result = utils.gen_ocs_commands([])
        defaults = [e for e in result if e.is_default_action and e.table == "ocs_schedule"]
        self.assertEqual(len(defaults), 1)
        self.assertEqual(defaults[0].action, "drop")

    def test_single_entry_format(self):
        result = utils.gen_ocs_commands([(2, 0, 1)])
        regular = [e for e in result if not e.is_default_action]
        self.assertEqual(len(regular), 1)
        e = regular[0]
        self.assertEqual(e.table, "ocs_schedule")
        self.assertEqual(e.action, "ocs_forward")
        self.assertEqual(e.match_keys["ingress_port"], 0)
        self.assertEqual(e.match_keys["slice_id"], 2)
        self.assertEqual(e.action_params["egress_port"], 1)

    def test_multiple_entries(self):
        entries = [(0, 0, 1), (1, 1, 2), (2, 2, 0)]
        result = utils.gen_ocs_commands(entries)
        regular = [e for e in result if not e.is_default_action]
        self.assertEqual(len(regular), 3)

    def test_default_set_before_entries(self):
        result = utils.gen_ocs_commands([(0, 0, 1)])
        self.assertTrue(result[0].is_default_action)
        self.assertFalse(result[1].is_default_action)


# ---------------------------------------------------------------------------
# tor_table_ip_to_dst
# ---------------------------------------------------------------------------

class TestTorTableIpToDst(unittest.TestCase):

    def test_empty_dict_returns_empty_list(self):
        self.assertEqual(utils.tor_table_ip_to_dst({}), [])

    def test_single_mapping(self):
        result = utils.tor_table_ip_to_dst({"10.0.0.1": 0})
        self.assertEqual(len(result), 1)
        e = result[0]
        self.assertEqual(e.table, "ip_to_dst_node")
        self.assertEqual(e.action, "write_dst")
        self.assertEqual(e.match_keys["ip"], "10.0.0.1")
        self.assertEqual(e.action_params["dst_node"], 0)

    def test_multiple_mappings(self):
        ip_map = {"10.0.0.1": 0, "10.0.1.1": 1, "10.0.2.1": 2}
        result = utils.tor_table_ip_to_dst(ip_map)
        self.assertEqual(len(result), 3)
        ips = [e.match_keys["ip"] for e in result]
        self.assertIn("10.0.0.1", ips)
        self.assertIn("10.0.1.1", ips)


# ---------------------------------------------------------------------------
# tor_table_arrive_at_dst
# ---------------------------------------------------------------------------

class TestTorTableArriveAtDst(unittest.TestCase):

    def test_format(self):
        result = utils.tor_table_arrive_at_dst(tor_id=3, to_host_port=1)
        self.assertEqual(len(result), 1)
        e = result[0]
        self.assertEqual(e.table, "arrive_at_dst")
        self.assertEqual(e.action, "send_to_host")
        self.assertEqual(e.match_keys["tor_id"], 3)
        self.assertEqual(e.action_params["host_port"], 1)

    def test_different_values(self):
        for tor_id in range(4):
            result = utils.tor_table_arrive_at_dst(tor_id=tor_id, to_host_port=2)
            self.assertEqual(result[0].match_keys["tor_id"], tor_id)
            self.assertEqual(result[0].action_params["host_port"], 2)


# ---------------------------------------------------------------------------
# tor_table_verify_desired_node
# ---------------------------------------------------------------------------

class TestTorTableVerifyDesiredNode(unittest.TestCase):

    def test_contains_tor_id(self):
        result = utils.tor_table_verify_desired_node(tor_id=5)
        tor_ids = [e.match_keys["tor_id"] for e in result]
        self.assertIn(5, tor_ids)

    def test_contains_wildcard_255(self):
        result = utils.tor_table_verify_desired_node(tor_id=0)
        tor_ids = [e.match_keys["tor_id"] for e in result]
        self.assertIn(255, tor_ids)

    def test_two_entries_generated(self):
        result = utils.tor_table_verify_desired_node(tor_id=0)
        self.assertEqual(len(result), 2)

    def test_both_are_noaction(self):
        result = utils.tor_table_verify_desired_node(tor_id=3)
        for e in result:
            self.assertEqual(e.action, "NoAction")
            self.assertEqual(e.table, "verify_desired_node")


# ---------------------------------------------------------------------------
# tor_table_routing_per_hop
# ---------------------------------------------------------------------------

class TestTorTableRoutingPerHop(unittest.TestCase):

    def _entry(self, dst, arrival_ts, cur_node, send_port, send_ts):
        hop = TimeFlowHop(cur_node=cur_node, send_port=send_port, send_ts=send_ts)
        return TimeFlowEntry(dst=dst, arrival_ts=arrival_ts, hops=hop)

    def test_specific_arrival_ts(self):
        entry = self._entry(dst=1, arrival_ts=2, cur_node=0, send_port=1, send_ts=2)
        result = utils.tor_table_routing_per_hop(entry)
        self.assertEqual(len(result), 1)
        e = result[0]
        self.assertEqual(e.table, "per_hop_routing")
        self.assertEqual(e.action, "write_time_flow_entry")
        self.assertEqual(e.match_keys["dst"], 1)
        self.assertEqual(e.match_keys["arrival_ts"], 2)
        self.assertEqual(e.action_params["cur_node"], 0)
        self.assertEqual(e.action_params["send_ts"], 2)
        self.assertEqual(e.action_params["send_port"], 1)

    def test_wildcard_arrival_ts_generates_per_slice_entries(self):
        hop = TimeFlowHop(cur_node=0, send_port=1, send_ts=0)
        entry = TimeFlowEntry(dst=1, arrival_ts=None, hops=hop)
        result = utils.tor_table_routing_per_hop(entry, nb_time_slices=4)
        self.assertEqual(len(result), 4)
        # Wildcard: match key arrival_ts == action param send_ts for each slice
        for i, e in enumerate(result):
            self.assertEqual(e.match_keys["arrival_ts"], i)
            self.assertEqual(e.action_params["send_ts"], i)


# ---------------------------------------------------------------------------
# tor_table_routing_source
# ---------------------------------------------------------------------------

class TestTorTableRoutingSource(unittest.TestCase):

    def _entry(self, dst, arrival_ts, hops):
        return TimeFlowEntry(dst=dst, arrival_ts=arrival_ts, hops=hops)

    def test_single_hop_specific_ts(self):
        hop = TimeFlowHop(cur_node=0, send_port=1, send_ts=1)
        entry = self._entry(dst=2, arrival_ts=1, hops=hop)
        result = utils.tor_table_routing_source(entry)
        self.assertEqual(len(result), 1)
        e = result[0]
        self.assertEqual(e.table, "add_source_routing_entries")
        self.assertEqual(e.action, "write_ssrr_header_0")  # 1 hop → index 0
        self.assertEqual(e.match_keys["dst"], 2)
        self.assertEqual(e.match_keys["arrival_ts"], 1)
        hops = e.action_params["hops"]
        self.assertEqual(len(hops), 1)
        self.assertEqual(hops[0], (0, 1, 1))  # (cur_node, send_ts, send_port)

    def test_two_hop_uses_header_1(self):
        hops = [
            TimeFlowHop(cur_node=0, send_port=1, send_ts=0),
            TimeFlowHop(cur_node=1, send_port=0, send_ts=1),
        ]
        entry = self._entry(dst=2, arrival_ts=0, hops=hops)
        result = utils.tor_table_routing_source(entry)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].action, "write_ssrr_header_1")
        self.assertEqual(len(result[0].action_params["hops"]), 2)

    def test_wildcard_arrival_ts_generates_per_slice_entries(self):
        hop = TimeFlowHop(cur_node=0, send_port=1, send_ts=0)
        entry = self._entry(dst=1, arrival_ts=None, hops=hop)
        result = utils.tor_table_routing_source(entry, nb_time_slices=3)
        self.assertEqual(len(result), 3)
        for i, e in enumerate(result):
            self.assertEqual(e.match_keys["arrival_ts"], i)
            # In wildcard mode send_ts = arrival_ts
            self.assertEqual(e.action_params["hops"][0][1], i)


# ---------------------------------------------------------------------------
# path2entries
# ---------------------------------------------------------------------------

class TestPath2Entries(unittest.TestCase):

    def test_per_hop_trims_to_first_step(self):
        steps = [
            Step(cur_node=0, step_type="port", send_port=1, send_ts=0, send_node=1),
            Step(cur_node=1, step_type="port", send_port=0, send_ts=1, send_node=2),
        ]
        path = Path(src=0, arrival_ts=0, dst=2, steps=steps)
        entries = utils.path2entries([path], routing_mode="Per-hop")
        self.assertEqual(len(entries[0][0].hops), 1)

    def test_source_keeps_all_steps(self):
        steps = [
            Step(cur_node=0, step_type="port", send_port=1, send_ts=0, send_node=1),
            Step(cur_node=1, step_type="port", send_port=0, send_ts=1, send_node=2),
        ]
        path = Path(src=0, arrival_ts=0, dst=2, steps=steps)
        entries = utils.path2entries([path], routing_mode="Source")
        self.assertEqual(len(entries[0][0].hops), 2)

    def test_to_mode_send_ts_is_actual_ts(self):
        path = _simple_path(src=0, dst=1, arrival_ts=0, send_port=0, send_ts=2)
        entries = utils.path2entries([path], routing_mode="Per-hop", arch_mode="TO")
        hop = entries[0][0].hops[0]
        self.assertEqual(hop.send_ts, 2)

    def test_ta_mode_send_ts_is_dst(self):
        path = _simple_path(src=0, dst=3, arrival_ts=0, send_port=0, send_ts=2)
        entries = utils.path2entries([path], routing_mode="Per-hop", arch_mode="TA")
        hop = entries[0][0].hops[0]
        self.assertEqual(hop.send_ts, 3)  # dst, not send_ts

    def test_grouping_by_src(self):
        paths = [
            _simple_path(src=0, dst=1, arrival_ts=0),
            _simple_path(src=0, dst=2, arrival_ts=0),
            _simple_path(src=1, dst=0, arrival_ts=0),
        ]
        entries = utils.path2entries(paths, routing_mode="Per-hop")
        self.assertEqual(len(entries[0]), 2)
        self.assertEqual(len(entries[1]), 1)

    def test_invalid_arch_mode_raises(self):
        path = _simple_path()
        with self.assertRaises(AssertionError):
            utils.path2entries([path], routing_mode="Per-hop", arch_mode="INVALID")

    def test_node_step_in_ta_mode_raises(self):
        step = Step(cur_node=0, step_type="node", send_node=1)
        path = Path(src=0, arrival_ts=0, dst=1, steps=[step])
        with self.assertRaises(AssertionError):
            utils.path2entries([path], routing_mode="Source", arch_mode="TA")


# ---------------------------------------------------------------------------
# metric_to_matrix
# ---------------------------------------------------------------------------

class TestMetricToMatrix(unittest.TestCase):

    def test_single_switch_single_queue(self):
        metric = {"tor0": {"pq_depth": {(0, 1): 42}}}
        result = utils.metric_to_matrix(metric)
        self.assertEqual(result[(0, 1)], 42)

    def test_multiple_switches(self):
        metric = {
            "tor0": {"pq_depth": {(0, 1): 10, (0, 2): 5}},
            "tor1": {"pq_depth": {(0, 0): 20}},
        }
        result = utils.metric_to_matrix(metric)
        self.assertEqual(result[(0, 1)], 10)
        self.assertEqual(result[(0, 2)], 5)
        self.assertEqual(result[(1, 0)], 20)

    def test_empty_metric(self):
        self.assertEqual(utils.metric_to_matrix({}), {})


if __name__ == "__main__":
    unittest.main()
