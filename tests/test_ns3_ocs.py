# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# License: Creative Commons NC BY SA 4.0
#
# OCS behaviour tests.  Exercise openoptics::OcsApp through its Python
# bindings in isolation (no ToR, no host), plus a workflow-level case that
# pushes the real `gen_ocs_commands` output into the backend and checks the
# resulting C++ state.

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import unittest
from unittest.mock import patch

from tests.ns3_helpers import skip_if_no_ns3, ns3_available


@skip_if_no_ns3
class OcsAppUnitTests(unittest.TestCase):
    """Hand-crafted schedules exercised directly against OcsApp."""

    def _make_ocs(self, nb_ports=4, nb_slices=3, slice_us=10_000):
        """Build an OCS node with `nb_ports` P2P uplinks.

        Returns:
          (ns module, OcsApp, list of peer NetDevices).

        Injecting into port i is `peers[i].Send(pkt, broadcast, 0x0800)` —
        the channel delivers the packet to the OCS-side NetDevice, whose
        promiscuous protocol handler fires OcsApp::ReceiveFromPort.
        """
        from ns import ns
        node = ns.CreateObject["ns3::Node"]()
        ocs = ns.CreateObject["ns3::openoptics::OcsApp"]()
        node.AddApplication(ocs)
        ocs.SetSliceDurationUs(slice_us)
        ocs.SetNumSlices(nb_slices)
        ocs.SetStartTime(ns.Seconds(0.0))

        p2p = ns.PointToPointHelper()
        p2p.SetDeviceAttribute("DataRate", ns.StringValue("1Gbps"))
        p2p.SetChannelAttribute("Delay", ns.TimeValue(ns.MicroSeconds(1)))
        peers_container = ns.NodeContainer(); peers_container.Create(nb_ports)
        peer_devs = []
        for i in range(nb_ports):
            devs = p2p.Install(node, peers_container.Get(i))
            ocs.AddPort(devs.Get(0))
            peer_devs.append(devs.Get(1))
        return ns, ocs, peer_devs

    def tearDown(self):
        if ns3_available():
            from ns import ns
            ns.Simulator.Destroy()

    def test_schedule_miss_drops(self):
        ns, ocs, peers = self._make_ocs()
        ns.Simulator.Stop(ns.MilliSeconds(1))
        pkt = ns.Create["ns3::Packet"](64)
        peers[0].Send(pkt, peers[0].GetBroadcast(), 0x0800)
        ns.Simulator.Run()
        self.assertEqual(ocs.GetDropCount(), 1)
        self.assertEqual(ocs.GetForwardCount(), 0)

    def test_exact_slice_match_forwards(self):
        ns, ocs, peers = self._make_ocs()
        ocs.AddScheduleEntry(0, 0, 1)
        ns.Simulator.Stop(ns.MilliSeconds(1))
        peers[0].Send(ns.Create["ns3::Packet"](64),
                      peers[0].GetBroadcast(), 0x0800)
        ns.Simulator.Run()
        self.assertEqual(ocs.GetDropCount(), 0)
        self.assertEqual(ocs.GetForwardCount(), 1)

    def test_schedule_rotates_with_sim_time(self):
        ns, ocs, peers = self._make_ocs(slice_us=10_000, nb_slices=3)
        ocs.AddScheduleEntry(0, 0, 1)
        ocs.AddScheduleEntry(0, 1, 2)

        # cppyy doesn't accept Python callbacks for Simulator::Schedule, so
        # advance the simulator in chunks and inject between them. Inject #1
        # in slice 0 (t=0 => out_port=1), advance to slice 1, inject #2
        # (should go to out_port=2 via the second schedule entry).
        peers[0].Send(ns.Create["ns3::Packet"](64),
                      peers[0].GetBroadcast(), 0x0800)
        ns.Simulator.Stop(ns.MilliSeconds(5))
        ns.Simulator.Run()
        fwd_after_slice0 = ocs.GetForwardCount()

        # Advance well past the slice boundary, then inject again.
        ns.Simulator.Stop(ns.MilliSeconds(12))
        ns.Simulator.Run()
        self.assertTrue(
            ns.Simulator.Now().GetMilliSeconds() >= 10,
            f"expected to be past slice boundary, got "
            f"{ns.Simulator.Now().GetMilliSeconds()}ms",
        )
        # Now inject at current sim time (which is in slice 1).
        peers[0].Send(ns.Create["ns3::Packet"](64),
                      peers[0].GetBroadcast(), 0x0800)
        # Give the packet time to propagate + be forwarded.
        ns.Simulator.Stop(ns.MilliSeconds(19))
        ns.Simulator.Run()

        self.assertEqual(fwd_after_slice0, 1)
        self.assertEqual(ocs.GetForwardCount(), 2)
        self.assertEqual(ocs.GetDropCount(), 0)

    def test_clear_schedule_drops_all(self):
        ns, ocs, peers = self._make_ocs()
        ocs.AddScheduleEntry(0, 0, 1)
        ocs.ClearSchedule()
        self.assertEqual(ocs.GetScheduleEntryCount(), 0)
        peers[0].Send(ns.Create["ns3::Packet"](64),
                      peers[0].GetBroadcast(), 0x0800)
        ns.Simulator.Stop(ns.MilliSeconds(1))
        ns.Simulator.Run()
        self.assertEqual(ocs.GetDropCount(), 1)
        self.assertEqual(ocs.GetForwardCount(), 0)

    def test_guardband_passes_light_window(self):
        """With a 2ms guardband on a 10ms slice, the light window is
        offset 0..7_999us. A packet sent near t=0 should forward."""
        ns, ocs, peers = self._make_ocs(slice_us=10_000, nb_slices=3)
        ocs.SetGuardbandUs(2_000)
        ocs.AddScheduleEntry(0, 0, 1)

        # Inject at t=0 (offset 0us, inside the 8ms light window).
        peers[0].Send(ns.Create["ns3::Packet"](64),
                      peers[0].GetBroadcast(), 0x0800)
        ns.Simulator.Stop(ns.MicroSeconds(500))
        ns.Simulator.Run()

        self.assertEqual(ocs.GetForwardCount(), 1)
        self.assertEqual(ocs.GetDropCount(), 0)

    def test_guardband_drops_dark_window(self):
        """With a 2ms guardband on a 10ms slice, the dark window is the
        final 2ms of every slice (offset 8_000..9_999us). A packet that
        arrives at offset 8_500us must be dropped even though the
        schedule entry exists."""
        ns, ocs, peers = self._make_ocs(slice_us=10_000, nb_slices=3)
        ocs.SetGuardbandUs(2_000)
        ocs.AddScheduleEntry(0, 0, 1)

        # Advance to t=8_500us — inside the tail 2ms dark window of
        # slice 0. The 1us channel delay still lands the packet at the
        # OCS at offset ~8_501us, well past the 8_000us boundary.
        ns.Simulator.Stop(ns.MicroSeconds(8_500))
        ns.Simulator.Run()
        peers[0].Send(ns.Create["ns3::Packet"](64),
                      peers[0].GetBroadcast(), 0x0800)
        ns.Simulator.Stop(ns.MicroSeconds(9_000))
        ns.Simulator.Run()

        self.assertEqual(ocs.GetForwardCount(), 0)
        self.assertEqual(ocs.GetDropCount(), 1)


@skip_if_no_ns3
class OcsGuardbandBaseNetworkTests(unittest.TestCase):
    """Full-pipeline guardband behaviour at the BaseNetwork level.

    Covers the headline invariant from the ns-3 review: when
    `guardband_ms` swallows the slice, the user gets a RuntimeWarning
    and a zero-throughput run rather than a crash or (worse) misrouted
    traffic.
    """

    def setUp(self):
        os.environ["OPENOPTICS_NS3_NO_PAUSE"] = "1"
        os.environ["OPENOPTICS_NS3_NO_REPORT"] = "1"

    def tearDown(self):
        os.environ.pop("OPENOPTICS_NS3_NO_REPORT", None)
        if ns3_available():
            from ns import ns
            ns.Simulator.Destroy()

    def test_guardband_exceeds_slice_warns_and_zero_throughput(self):
        import warnings
        from openoptics import OpticalTopo, OpticalRouting, Toolbox
        from openoptics.backends.ns3.backend import Ns3Backend

        nb_node = 2
        backend = Ns3Backend()
        num_packets = 5
        with patch("openoptics.Toolbox.create_backend", return_value=backend):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                net = Toolbox.BaseNetwork(
                    name="guardband_oversize", backend="ns3",
                    nb_node=nb_node,
                    time_slice_duration_us=5_000,
                    guardband_ms=10,   # 10_000 us guardband > 5_000 us slice
                    use_webserver=False,
                    simulation_stop_s=0.1,
                )
                net.deploy_topo(OpticalTopo.round_robin(nb_node=nb_node))
                paths = OpticalRouting.routing_direct(net.get_topo())
                net.deploy_routing(paths, routing_mode="Per-hop")
            matching = [
                w for w in caught
                if issubclass(w.category, RuntimeWarning)
                and "guardband_us" in str(w.message)
            ]
            self.assertTrue(
                matching,
                f"expected RuntimeWarning about guardband_us, got {caught!r}",
            )
            net.udp_traffic().echo(
                0, 1, start_s=0.001, stop_s=0.08,
                num_packets=num_packets, interval_s=0.005,
            ).install()
            net.start()

        # Every packet should be dropped somewhere — either by the ToR
        # byte-budget admission (effective active = 0) or by the OCS
        # dark window — but zero packets should cross end-to-end.
        delivered = sum(
            int(backend._tor_apps[t].GetDeliveredToHostCount())
            for t in backend._tor_apps
        )
        self.assertEqual(delivered, 0)
        self.assertEqual(int(backend._ocs_app.GetForwardCount()), 0)

        # Proof that the zero delivery is from enforced rejection, not
        # absence of traffic: the source ToR ingested packets but none
        # made it to a destination ToR's host. Packets that can't pass
        # admission (effective active = 0 means CanFinishInActiveWindow
        # always rejects) either drop with overflow or stay queued in
        # the calendar queue across cycles — both prove enforcement.
        ingress_total = sum(
            int(backend._tor_apps[t].GetIngressFromHostCount())
            for t in backend._tor_apps
        )
        self.assertGreater(
            ingress_total, 0,
            "expected at least one packet to enter the system",
        )
        held_or_dropped = (
            sum(int(backend._tor_apps[t].GetSliceOverflowDrops())
                for t in backend._tor_apps)
            + sum(int(backend._tor_apps[t].GetTotalQueueDepth())
                  for t in backend._tor_apps)
            + int(backend._ocs_app.GetDropCount())
        )
        self.assertGreater(
            held_or_dropped, 0,
            "expected enforced rejection (overflow drop, OCS dark drop, "
            "or packets stuck in CQ across cycles)",
        )


@skip_if_no_ns3
class OcsGeneratedScheduleTests(unittest.TestCase):
    """OCS tests that drive the real `utils.gen_ocs_commands` output."""

    def test_load_generated_round_robin_schedule(self):
        from openoptics import utils, OpticalTopo
        from openoptics.backends.ns3.backend import Ns3Backend

        nb_node = 4
        circuits = OpticalTopo.round_robin(nb_node=nb_node)

        # Build schedule input for gen_ocs_commands: it expects a list of
        # (slice_id, port_src, port_dst) tuples, derived by deploy_topo /
        # setup_ocs. Reconstruct manually for this test.
        ocs_slice_port1_port2 = []
        for ts, n1, n2, p1, p2 in circuits:
            if n1 == -1 or n2 == -1:
                continue
            ocs_slice_port1_port2.append((ts, n1, n2))
            ocs_slice_port1_port2.append((ts, n2, n1))
        entries = utils.gen_ocs_commands(ocs_slice_port1_port2)
        # Entries are a mix of 1 default-action drop + N ocs_forward.
        non_default = [e for e in entries if not e.is_default_action]

        # Use the full backend so setup() builds an OCS with proper nb_ports.
        from openoptics import Toolbox
        backend = Ns3Backend()
        with patch("openoptics.Toolbox.create_backend", return_value=backend):
            net = Toolbox.BaseNetwork(
                name="ocs_gen_test", backend="ns3", nb_node=nb_node,
                time_slice_duration_us=10_000, guardband_ms=0,
                use_webserver=False,
            )
            net.deploy_topo(circuits)

        self.assertEqual(
            backend._ocs_app.GetScheduleEntryCount(), len(non_default)
        )
        # Spot-check: pick one entry and verify the C++ LUT returns the
        # same egress port.
        sample = non_default[0]
        got = backend._ocs_app.LookupSchedule(
            int(sample.match_keys["ingress_port"]),
            int(sample.match_keys["slice_id"]),
        )
        self.assertEqual(got, int(sample.action_params["egress_port"]))

        backend.stop()
        backend.cleanup()

    def test_deploy_topo_workflow(self):
        """End-to-end setup()+clear_table()+load_table() via deploy_topo."""
        from openoptics import OpticalTopo, Toolbox
        from openoptics.backends.ns3.backend import Ns3Backend

        nb_node = 4
        backend = Ns3Backend()
        with patch("openoptics.Toolbox.create_backend", return_value=backend):
            net = Toolbox.BaseNetwork(
                name="deploy_topo_test", backend="ns3", nb_node=nb_node,
                time_slice_duration_us=10_000, guardband_ms=0,
                use_webserver=False,
            )
            self.assertTrue(
                net.deploy_topo(OpticalTopo.round_robin(nb_node=nb_node))
            )

        self.assertTrue(backend._ocs_app.GetScheduleEntryCount() > 0)
        # IP-to-tor populated during setup()
        self.assertEqual(
            backend.get_ip_to_tor(),
            {f"10.0.{i}.1": i for i in range(nb_node)},
        )
        # All tor switches registered
        self.assertEqual(len(backend.get_tor_switches()), nb_node)
        for i in range(nb_node):
            self.assertTrue(backend.switch_exists(f"tor{i}"))
        self.assertTrue(backend.switch_exists("ocs"))

        backend.stop()
        backend.cleanup()


if __name__ == "__main__":
    unittest.main()
