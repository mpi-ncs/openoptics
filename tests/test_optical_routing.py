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

    def test_random_true_emits_sentinel_hop0(self):
        """random=True should emit all-255 sentinel for hop0 on indirect paths."""
        paths = OpticalRouting.routing_vlb(
            self.slice_to_topo, self.tor_to_ocs_port, random=True)
        indirect = [p for p in paths if len(p.steps) == 2]
        self.assertGreater(len(indirect), 0, "Should have at least one indirect path")
        for p in indirect:
            hop0 = p.steps[0]
            self.assertEqual(hop0.step_type, "port")
            self.assertEqual(hop0.send_port, 255)
            self.assertEqual(hop0.send_ts, 255)
            self.assertEqual(hop0.cur_node, 255)

    def test_random_false_emits_concrete_hop0(self):
        """random=False (default) should emit concrete port/ts for hop0."""
        paths = OpticalRouting.routing_vlb(
            self.slice_to_topo, self.tor_to_ocs_port, random=False)
        indirect = [p for p in paths if len(p.steps) == 2]
        self.assertGreater(len(indirect), 0)
        for p in indirect:
            hop0 = p.steps[0]
            self.assertEqual(hop0.step_type, "port")
            self.assertNotEqual(hop0.send_port, 255)
            self.assertNotEqual(hop0.send_ts, 255)

    def test_random_direct_paths_unchanged(self):
        """random=True should not affect direct (1-hop) paths."""
        paths_det = OpticalRouting.routing_vlb(
            self.slice_to_topo, self.tor_to_ocs_port, random=False)
        paths_rng = OpticalRouting.routing_vlb(
            self.slice_to_topo, self.tor_to_ocs_port, random=True)
        direct_det = [(p.src, p.dst, p.arrival_ts, p.steps[0].send_port, p.steps[0].send_ts)
                      for p in paths_det if len(p.steps) == 1]
        direct_rng = [(p.src, p.dst, p.arrival_ts, p.steps[0].send_port, p.steps[0].send_ts)
                      for p in paths_rng if len(p.steps) == 1]
        self.assertEqual(sorted(direct_det), sorted(direct_rng))


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


# ---------------------------------------------------------------------------
# routing_hoho — optimal substructure & no forwarding loops
# ---------------------------------------------------------------------------

def _opera_4node_1link_topo():
    """4-node, 1-link opera schedule with guardband slots."""
    circuits = OpticalTopo.opera(nb_node=4, nb_link=1, guardband=True)
    return _build_slice_to_topo(4, circuits)


def _opera_4node_2link_topo():
    """4-node, 2-link opera schedule with guardband slots."""
    circuits = OpticalTopo.opera(nb_node=4, nb_link=2, guardband=True)
    return _build_slice_to_topo(4, circuits)


def _hoho_per_hop_table(slice_to_topo, max_hop=2):
    """Return (tor, cs, dst) -> (send_ts, send_port, next_tor)."""
    from openoptics import utils
    paths = OpticalRouting.routing_hoho(slice_to_topo, max_hop=max_hop)
    per_src = utils.path2entries(paths, routing_mode="Per-hop")
    table = {}
    for src, entries in per_src.items():
        for e in entries:
            hop = e.hops[0]
            # In DiGraph, find the next_tor such that (src, next_tor) edge at
            # slot=hop.send_ts has port1 == hop.send_port_or_node.
            slot_topo = slice_to_topo[hop.send_ts]
            next_tor = None
            for cand in slot_topo.neighbors(src):
                if slot_topo[src][cand].get("port1") == hop.send_port_or_node:
                    next_tor = cand
                    break
            table[(src, e.arrival_ts, e.dst)] = (
                hop.send_ts,
                hop.send_port_or_node,
                next_tor,
            )
    return table


class TestRoutingHohoOptimalSubstructure(unittest.TestCase):

    def test_hoho_no_forwarding_loops_1link(self):
        """Simulate forwarding from every (tor, cs, dst) entry; assert the
        chain terminates at dst within nb_ts*3 steps without revisits."""
        slice_to_topo = _opera_4node_1link_topo()
        nb_ts = len(slice_to_topo)
        table = _hoho_per_hop_table(slice_to_topo, max_hop=2)

        for (tor, cs, dst), (send_ts, _port, next_tor) in list(table.items()):
            self.assertIsNotNone(next_tor,
                f"entry ({tor}, cs={cs}, dst={dst}) has no resolvable next_tor")
            visited = set()
            cur, ccs = tor, cs
            for _step in range(nb_ts * 3):
                if cur == dst:
                    break
                self.assertNotIn((cur, ccs), visited,
                    f"loop detected while forwarding packet from ({tor}, cs={cs}) "
                    f"to dst={dst}: revisit ({cur}, ccs={ccs})")
                visited.add((cur, ccs))
                entry = table.get((cur, ccs, dst))
                self.assertIsNotNone(entry,
                    f"no entry for ({cur}, cs={ccs}, dst={dst}) "
                    f"while forwarding from ({tor}, cs={cs})")
                e_send_ts, _e_port, e_next = entry
                self.assertIsNotNone(e_next,
                    f"entry ({cur}, cs={ccs}, dst={dst}) has no next_tor")
                # Packet lands at e_next with cur_slice = e_send_ts
                # (same-slot transmit assumption, matches the runtime).
                cur, ccs = e_next, e_send_ts
            else:
                self.fail(
                    f"forwarding chain from ({tor}, cs={cs}) to dst={dst} did "
                    f"not terminate within {nb_ts*3} steps")

    def test_hoho_no_forwarding_loops_2link(self):
        """Same invariant on the 4-node 2-link schedule."""
        slice_to_topo = _opera_4node_2link_topo()
        nb_ts = len(slice_to_topo)
        table = _hoho_per_hop_table(slice_to_topo, max_hop=2)

        for (tor, cs, dst), (send_ts, _port, next_tor) in list(table.items()):
            self.assertIsNotNone(next_tor)
            visited = set()
            cur, ccs = tor, cs
            for _ in range(nb_ts * 3):
                if cur == dst:
                    break
                self.assertNotIn((cur, ccs), visited,
                    f"loop from ({tor}, cs={cs}) to dst={dst}")
                visited.add((cur, ccs))
                entry = table.get((cur, ccs, dst))
                self.assertIsNotNone(entry)
                cur, ccs = entry[2], entry[0]
            else:
                self.fail(f"chain from ({tor}, cs={cs}) to dst={dst} did not terminate")

    def test_hoho_known_loop_repaired(self):
        """On the 4-node 1-link schedule (the historical bug fixture):

        - (tor0, cs=0, dst=tor1) stays as the 2-slot multi-hop plan
          (first step: slot 0 via tor3, since that's the true shortest).
        - (tor3, cs=0, dst=tor1) must NOT be "slot 0 via tor0" (the old
          loop-generating entry); it should be "slot 2 direct → tor1"
          which is the substructure of tor0's 2-hop plan and also the
          optimal wait-then-direct at tor3.
        """
        slice_to_topo = _opera_4node_1link_topo()
        table = _hoho_per_hop_table(slice_to_topo, max_hop=2)

        # tor0 at cs=0 for dst=tor1: 2-hop via tor3 at slot 0
        self.assertIn((0, 0, 1), table)
        send_ts_0, _, next_0 = table[(0, 0, 1)]
        self.assertEqual(send_ts_0, 0,
            "tor0 cs=0 dst=tor1 should transmit at slot 0 (via tor3)")
        self.assertEqual(next_0, 3,
            "tor0 cs=0 dst=tor1 first hop should be to tor3")

        # tor3 at cs=0 for dst=tor1: must be direct slot 2 (the subpath)
        self.assertIn((3, 0, 1), table)
        send_ts_3, _, next_3 = table[(3, 0, 1)]
        self.assertEqual(send_ts_3, 2,
            "tor3 cs=0 dst=tor1 should transmit at slot 2 (direct), not slot 0")
        self.assertEqual(next_3, 1,
            "tor3 cs=0 dst=tor1 should go direct to tor1, not back to tor0")

    def test_hoho_optimal_substructure_for_multi_hop_paths(self):
        """For every multi-hop HoHo path (src, cs, dst) with steps
        [step0, step1, ...], the first-step landing state (step0.send_node,
        cs'=step0.send_ts) must have a Per-hop entry whose first transmit
        matches step1 exactly.  I.e., the intermediate's entry is the
        subpath of the source's plan.
        """
        slice_to_topo = _opera_4node_1link_topo()
        paths = OpticalRouting.routing_hoho(slice_to_topo, max_hop=2)
        # Per-hop entries from path2entries (keys on path.src, arrival_ts, dst)
        per_hop_first = {}
        for p in paths:
            s0 = p.steps[0]
            per_hop_first[(p.src, p.arrival_ts, p.dst)] = (
                s0.send_ts, s0.send_port, s0.send_node)

        for p in paths:
            if len(p.steps) < 2:
                continue
            # Subpath invariant: the intermediate's entry for (cs=s0.send_ts,
            # dst=p.dst) must start with exactly s1.
            s0, s1 = p.steps[0], p.steps[1]
            inter = s0.send_node
            sub_key = (inter, s0.send_ts, p.dst)
            self.assertIn(sub_key, per_hop_first,
                f"intermediate {inter} has no entry at cs={s0.send_ts} for "
                f"dst={p.dst} — path {p.src}->{inter}->{s1.send_node}... is broken")
            sub_send_ts, sub_port, sub_next = per_hop_first[sub_key]
            self.assertEqual(sub_send_ts, s1.send_ts,
                f"substructure mismatch: {p.src} path says {inter} should "
                f"send at slot {s1.send_ts}, but {inter}'s own entry says "
                f"slot {sub_send_ts}")
            self.assertEqual(sub_next, s1.send_node,
                f"substructure mismatch: {p.src} path says {inter} should "
                f"forward to {s1.send_node}, but {inter}'s own entry says "
                f"{sub_next}")

    def test_hoho_never_worse_than_direct(self):
        """For every (src, cs, dst) entry, the HoHo plan's total duration
        (from cs until the packet arrives at dst) must be ≤ the direct
        plan's duration.  Since the Dijkstra minimises duration and direct
        routing is a feasible (0 or 1 transmit) option in the same graph,
        this should always hold."""
        slice_to_topo = _opera_4node_1link_topo()
        nb_ts = len(slice_to_topo)
        table = _hoho_per_hop_table(slice_to_topo, max_hop=2)

        # Build a direct-routing reference: (src, dst, cs) -> (send_ts_absolute, duration)
        direct_ref = {}
        for s in range(4):
            for d in range(4):
                if s == d:
                    continue
                for dp in OpticalRouting.find_direct_path(slice_to_topo, s, d):
                    direct_ref[(s, dp.arrival_ts, d)] = dp.steps[0].send_ts

        def _dur_from(entry_table, tor, cs, dst, max_steps=None):
            if max_steps is None:
                max_steps = nb_ts * 3
            total = 0
            cur, ccs = tor, cs
            for _ in range(max_steps):
                if cur == dst:
                    return total
                entry = entry_table.get((cur, ccs, dst))
                if entry is None:
                    return None
                e_send_ts, _p, e_next = entry
                wait = (e_send_ts - ccs + nb_ts) % nb_ts
                total += wait
                cur, ccs = e_next, e_send_ts
            return None

        for (tor, cs, dst) in list(table.keys()):
            hoho_dur = _dur_from(table, tor, cs, dst)
            self.assertIsNotNone(hoho_dur,
                f"hoho chain from ({tor}, {cs}) to {dst} did not terminate")
            direct_send = direct_ref.get((tor, cs, dst))
            if direct_send is None:
                continue
            direct_dur = (direct_send - cs + nb_ts) % nb_ts
            self.assertLessEqual(hoho_dur, direct_dur,
                f"hoho worse than direct at ({tor}, cs={cs}, dst={dst}): "
                f"hoho dur={hoho_dur}, direct dur={direct_dur}")


if __name__ == "__main__":
    unittest.main()
