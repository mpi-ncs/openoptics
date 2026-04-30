# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# License: Creative Commons NC BY SA 4.0
#
# Scenario-level integration tests for the ns-3 backend. Each test drives
# a representative (topology, routing, routing_mode) combination through
# the full pipeline and asserts on both the per-switch counters and the
# FlowMonitor end-to-end numbers.
#
# These complement test_ns3_backend.py's end-to-end tests (which focus on
# round-robin + direct + per-hop) by exercising other combinations:
#
#   - Larger topology with sparse routing (8 nodes, 0<->1 only)
#   - Opera topology with multi-hop HoHo per-hop routing
#
# All tests conditional-skip when ns-3 unavailable.

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.ns3_helpers import skip_if_no_ns3, ns3_available


@skip_if_no_ns3
class Ns3ScenarioTests(unittest.TestCase):
    """Run each (topology, routing) scenario end-to-end and sanity-check
    the resulting counters + FlowMonitor stats."""

    def setUp(self):
        # Keep run() from blocking on input() even if the dashboard is on.
        os.environ["OPENOPTICS_NS3_NO_PAUSE"] = "1"
        # Silence the stdout report spam in the test output.
        os.environ["OPENOPTICS_NS3_NO_REPORT"] = "1"

    def tearDown(self):
        os.environ.pop("OPENOPTICS_NS3_NO_REPORT", None)
        if ns3_available():
            from ns import ns
            ns.Simulator.Destroy()

    def _install_and_run(self, net, backend, src, dst, num_packets=10,
                         start_s=0.01, stop_s=0.5, interval_s=0.02):
        net.udp_traffic().echo(
            src, dst, start_s=start_s, stop_s=stop_s,
            num_packets=num_packets, interval_s=interval_s,
        ).install()
        net.start()

    def _flow_stats(self, backend):
        """Pull (tx, rx, lost) totals across every observed flow."""
        ns = backend._ns
        backend._flow_monitor.CheckForLostPackets()
        classifier = ns.DynamicCast["ns3::Ipv4FlowClassifier"](
            backend._flow_helper.GetClassifier()
        )
        stats = backend._flow_monitor.GetFlowStats()
        tx = rx = lost = 0
        flows = []
        for flow_id, s in stats:
            tx += int(s.txPackets)
            rx += int(s.rxPackets)
            lost += int(s.lostPackets)
            t = classifier.FindFlow(flow_id)
            flows.append((
                str(t.sourceAddress), int(t.sourcePort),
                str(t.destinationAddress), int(t.destinationPort),
                int(s.txPackets), int(s.rxPackets), int(s.lostPackets),
            ))
        return tx, rx, lost, flows

    # ------------------------------------------------------------------
    # 8-node round-robin, direct routing, sparse flow (0 <-> 1 only).
    # Mirror of examples/ns3_routing_direct_2nodes.py.
    # ------------------------------------------------------------------
    def test_round_robin_8nodes_direct_2nodes(self):
        from openoptics import OpticalTopo, OpticalRouting, Toolbox
        from openoptics.backends.ns3.backend import Ns3Backend

        nb_node = 8
        num_packets = 10
        backend = Ns3Backend()
        with patch("openoptics.Toolbox.create_backend", return_value=backend):
            net = Toolbox.BaseNetwork(
                name="scenario_rr8_direct2", backend="ns3",
                nb_node=nb_node,
                time_slice_duration_us=5_000, guardband_ms=0,
                use_webserver=False, simulation_stop_s=0.5,
            )
            net.deploy_topo(OpticalTopo.round_robin(nb_node=nb_node))
            paths = OpticalRouting.find_direct_path(
                net.get_topo(), node1=0, node2=1)
            paths.extend(OpticalRouting.find_direct_path(
                net.get_topo(), node1=1, node2=0))
            net.deploy_routing(paths, routing_mode="Per-hop")
            self._install_and_run(net, backend, src=0, dst=1,
                                  num_packets=num_packets)

        # Traffic-bearing tors are 0 and 1. Others see nothing.
        self.assertEqual(backend._tor_apps[0].GetIngressFromHostCount(),
                         num_packets)
        self.assertEqual(backend._tor_apps[1].GetIngressFromHostCount(),
                         num_packets)
        for tor_id in range(2, nb_node):
            self.assertEqual(
                backend._tor_apps[tor_id].GetIngressFromHostCount(), 0)
            self.assertEqual(
                backend._tor_apps[tor_id].GetIngressFromUplinkCount(), 0)

        # No drops anywhere.
        self.assertEqual(backend._ocs_app.GetDropCount(), 0)
        for tor_id in range(nb_node):
            self.assertEqual(
                backend._tor_apps[tor_id].GetDropCount(), 0)

        # FlowMonitor sees exactly two flows (outbound + echo return),
        # each tx=rx=num_packets.
        tx, rx, lost, flows = self._flow_stats(backend)
        self.assertEqual(len(flows), 2)
        self.assertEqual(tx, 2 * num_packets)
        self.assertEqual(rx, 2 * num_packets)
        self.assertEqual(lost, 0)

    # ------------------------------------------------------------------
    # 4-node Opera, HoHo per-hop (multi-hop).
    # Mirror of examples/ns3_routing_hoho_perhop.py.
    # ------------------------------------------------------------------
    def test_opera_4nodes_hoho_perhop(self):
        from openoptics import OpticalTopo, OpticalRouting, Toolbox
        from openoptics.backends.ns3.backend import Ns3Backend

        nb_node = 4
        nb_link = 1
        num_packets = 10
        backend = Ns3Backend()
        with patch("openoptics.Toolbox.create_backend", return_value=backend):
            net = Toolbox.BaseNetwork(
                name="scenario_opera_hoho", backend="ns3",
                nb_node=nb_node, nb_link=nb_link,
                time_slice_duration_us=10_000, guardband_ms=0,
                ocs_tor_link_bw_gbps=0.02,
                use_webserver=False, simulation_stop_s=0.7,
            )
            net.deploy_topo(OpticalTopo.opera(
                nb_node=nb_node, nb_link=nb_link))
            paths = OpticalRouting.routing_hoho(net.get_topo())
            self.assertTrue(net.deploy_routing(paths, routing_mode="Per-hop"))
            self._install_and_run(net, backend, src=0, dst=2,
                                  num_packets=num_packets,
                                  stop_s=0.65)

        # Src (tor0) sees num_packets from its host.
        self.assertEqual(backend._tor_apps[0].GetIngressFromHostCount(),
                         num_packets)
        # Dst (tor2) eventually delivers all forward-direction packets.
        self.assertEqual(backend._tor_apps[2].GetDeliveredToHostCount(),
                         num_packets)

        # HoHo paths may go through an intermediate ToR. At least one
        # non-src/non-dst ToR should have from_uplink > 0 (2-hop case)
        # OR tor0 ships on a direct link (1-hop case). In both scenarios,
        # the OCS forwards at least num_packets * (hops_of_both_flows).
        hop_relays = sum(
            int(backend._tor_apps[t].GetIngressFromUplinkCount())
            for t in (1, 3)
            if t in backend._tor_apps
        )
        # Flow direction: tor0 → tor2 echo back tor2 → tor0. Arrival on
        # uplink at the destination counts too; subtract tor2 arrivals.
        # Don't over-constrain the assertion: just require no drops +
        # every packet delivered round-trip.
        self.assertEqual(backend._ocs_app.GetDropCount(), 0)
        for tor_id in range(nb_node):
            self.assertEqual(backend._tor_apps[tor_id].GetDropCount(), 0,
                             f"tor{tor_id} had drops")

        # Two flows; each num_packets tx = num_packets rx (round-trip).
        tx, rx, lost, flows = self._flow_stats(backend)
        self.assertEqual(len(flows), 2)
        self.assertEqual(tx, 2 * num_packets)
        self.assertEqual(rx, 2 * num_packets)
        self.assertEqual(lost, 0)


    # ------------------------------------------------------------------
    # Multi-link regression — guards the OCS port-encoding fix. Before
    # the fix, ns-3 registered OCS ports tor-major while Toolbox emits
    # them port-major, so any nb_link>1 topology would silently
    # misprogram the OCS. This test deploys a 4-node, 2-link Opera
    # topology and asserts that every schedule entry Toolbox generated
    # round-trips through the ns-3 OcsApp LUT at the expected port
    # index.
    # ------------------------------------------------------------------
    def test_multilink_ocs_schedule_roundtrip(self):
        from openoptics import OpticalTopo, Toolbox
        from openoptics.backends.ns3.backend import (
            Ns3Backend,
            ocs_port_index,
        )

        nb_node = 4
        nb_link = 2
        backend = Ns3Backend()
        with patch("openoptics.Toolbox.create_backend", return_value=backend):
            net = Toolbox.BaseNetwork(
                name="scenario_multilink",
                backend="ns3",
                nb_node=nb_node,
                nb_link=nb_link,
                time_slice_duration_us=10_000, guardband_ms=0,
                use_webserver=False,
                simulation_stop_s=0.05,
            )
            net.deploy_topo(OpticalTopo.opera(
                nb_node=nb_node, nb_link=nb_link))

        # Cross-reference every edge in slice_to_topo against the ns-3
        # LUT. Toolbox's setup_ocs loads both directions per edge, so we
        # check (port1 -> port2) and (port2 -> port1) in each slice.
        ocs = backend._ocs_app
        for slice_id, graph in net.slice_to_topo.items():
            for node1, node2, attr in graph.edges(data=True):
                p1 = net.cal_node_port_to_ocs_port(node1, attr["port1"])
                p2 = net.cal_node_port_to_ocs_port(node2, attr["port2"])
                self.assertEqual(p1, ocs_port_index(node1, attr["port1"],
                                                    nb_node))
                self.assertEqual(p2, ocs_port_index(node2, attr["port2"],
                                                    nb_node))
                self.assertEqual(int(ocs.LookupSchedule(p1, slice_id)), p2)
                self.assertEqual(int(ocs.LookupSchedule(p2, slice_id)), p1)


if __name__ == "__main__":
    unittest.main()
