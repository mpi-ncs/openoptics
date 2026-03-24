# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# This software is licensed for non-commercial scientific research purposes only.
# License text: Creative Commons NC BY SA 4.0

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from openoptics.TimeFlowTable import Path, Step, TimeFlowEntry, TimeFlowHop


class TestTimeFlowHop(unittest.TestCase):

    def test_send_port_stores_port_and_ts(self):
        hop = TimeFlowHop(cur_node=2, send_port=1, send_ts=3)
        self.assertEqual(hop.cur_node, 2)
        self.assertEqual(hop.send_port_or_node, 1)
        self.assertEqual(hop.send_ts, 3)

    def test_send_node_stores_node_and_sentinel_ts(self):
        hop = TimeFlowHop(cur_node=0, send_node=5)
        self.assertEqual(hop.send_port_or_node, 5)
        self.assertEqual(hop.send_ts, 255)  # sentinel for node-indexed hop

    def test_missing_cur_node_defaults_to_wildcard(self):
        hop = TimeFlowHop(send_port=0, send_ts=1)
        self.assertEqual(hop.cur_node, 255)

    def test_neither_port_nor_node_raises(self):
        with self.assertRaises(ValueError):
            TimeFlowHop(cur_node=0)

    def test_str_port_hop(self):
        hop = TimeFlowHop(cur_node=1, send_port=0, send_ts=2)
        text = str(hop)
        self.assertIn("1", text)
        self.assertIn("2", text)

    def test_str_node_hop(self):
        hop = TimeFlowHop(cur_node=1, send_node=3)
        text = str(hop)
        self.assertIn("3", text)


class TestTimeFlowEntry(unittest.TestCase):

    def test_single_hop_wrapped_in_list(self):
        hop = TimeFlowHop(send_port=0, send_ts=0)
        entry = TimeFlowEntry(dst=1, arrival_ts=0, hops=hop)
        self.assertIsInstance(entry.hops, list)
        self.assertEqual(len(entry.hops), 1)

    def test_list_of_hops_stored_as_is(self):
        hops = [TimeFlowHop(send_port=i, send_ts=i) for i in range(3)]
        entry = TimeFlowEntry(dst=2, arrival_ts=1, hops=hops)
        self.assertEqual(len(entry.hops), 3)

    def test_wildcard_arrival_ts(self):
        entry = TimeFlowEntry(dst=0, hops=TimeFlowHop(send_port=0, send_ts=0))
        self.assertIsNone(entry.arrival_ts)

    def test_invalid_hops_type_raises(self):
        with self.assertRaises(ValueError):
            TimeFlowEntry(dst=0, arrival_ts=0, hops="invalid")

    def test_str_contains_dst(self):
        entry = TimeFlowEntry(dst=7, arrival_ts=2, hops=TimeFlowHop(send_port=0, send_ts=0))
        self.assertIn("7", str(entry))


class TestStep(unittest.TestCase):

    def test_port_step(self):
        step = Step(cur_node=0, step_type="port", send_port=1, send_ts=2)
        self.assertEqual(step.step_type, "port")
        self.assertEqual(step.send_port, 1)
        self.assertEqual(step.send_ts, 2)

    def test_node_step(self):
        step = Step(cur_node=0, step_type="node", send_node=3)
        self.assertEqual(step.step_type, "node")
        self.assertEqual(step.send_node, 3)

    def test_invalid_step_type_raises(self):
        with self.assertRaises(AssertionError):
            Step(step_type="invalid")


class TestPath(unittest.TestCase):

    def _make_path(self, src=0, dst=1, arrival_ts=0):
        step = Step(cur_node=src, step_type="port", send_port=0, send_ts=arrival_ts)
        return Path(src=src, arrival_ts=arrival_ts, dst=dst, steps=[step])

    def test_attributes_stored(self):
        path = self._make_path(src=0, dst=3, arrival_ts=2)
        self.assertEqual(path.src, 0)
        self.assertEqual(path.dst, 3)
        self.assertEqual(path.arrival_ts, 2)
        self.assertEqual(len(path.steps), 1)

    def test_equality_same_key(self):
        p1 = self._make_path(0, 1, 0)
        p2 = self._make_path(0, 1, 0)
        self.assertEqual(p1, p2)

    def test_equality_different_arrival_ts(self):
        p1 = self._make_path(0, 1, 0)
        p2 = self._make_path(0, 1, 1)
        self.assertNotEqual(p1, p2)

    def test_hash_equal_for_same_key(self):
        p1 = self._make_path(0, 1, 0)
        p2 = self._make_path(0, 1, 0)
        self.assertEqual(hash(p1), hash(p2))

    def test_usable_as_dict_key(self):
        p = self._make_path(0, 1, 0)
        d = {p: "value"}
        self.assertEqual(d[p], "value")

    def test_ordering(self):
        paths = [self._make_path(0, 1, 2), self._make_path(0, 1, 0), self._make_path(0, 1, 1)]
        self.assertEqual(sorted(paths)[0], self._make_path(0, 1, 0))


if __name__ == "__main__":
    unittest.main()
