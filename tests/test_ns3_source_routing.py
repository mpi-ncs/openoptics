# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# License: Creative Commons NC BY SA 4.0
#
# Source-routing tests for the ns-3 backend.
#
# Covers three scenarios:
#   1. Direct 1-hop paths with routing_mode="Source" — the ingress ToR
#      stamps a single-hop header; the destination peels and delivers.
#   2. HoHo 2-hop paths with routing_mode="Source" — exercises the
#      intermediate-hop decrement + re-stamp logic.
#   3. VLB 2-hop paths with routing_mode="Source" (both random=False and
#      random=True) — exercises the node-type sentinel resolution (via
#      cal_port_slice_to_node) AND the random-port sentinel (via
#      UniformRandomVariable).
#
# Plus a low-level serialization test for OpenOpticsSourceRouteHeader and
# a dispatch test for the Ns3Backend translator.

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.ns3_helpers import skip_if_no_ns3, ns3_available


@skip_if_no_ns3
class SourceRouteHeaderUnitTests(unittest.TestCase):
    """Serialize -> deserialize round-trip of OpenOpticsSourceRouteHeader."""

    def tearDown(self):
        if ns3_available():
            from ns import ns
            ns.Simulator.Destroy()

    def test_roundtrip_preserves_hops_and_index(self):
        from ns import ns
        import cppyy

        HopT = "ns3::openoptics::OpenOpticsSourceRouteHeader::Hop"
        hops = cppyy.gbl.std.vector[HopT]()
        for cur_node, send_ts, send_port_or_node in ((0, 2, 0), (1, 3, 1)):
            h = ns.openoptics.OpenOpticsSourceRouteHeader.Hop()
            h.cur_node = cur_node
            h.send_ts = send_ts
            h.send_port_or_node = send_port_or_node
            hops.push_back(h)

        src = ns.openoptics.OpenOpticsSourceRouteHeader(hops)
        src.SetCurrentIdx(1)
        self.assertEqual(src.GetHopCount(), 2)
        self.assertEqual(src.GetCurrentIdx(), 1)
        # Hop 0 still intact
        self.assertEqual(src.GetHopAt(0).cur_node, 0)
        self.assertEqual(src.GetHopAt(0).send_ts, 2)
        self.assertEqual(src.GetHopAt(0).send_port_or_node, 0)

        # Roundtrip through Packet buffer.
        pkt = ns.Create["ns3::Packet"](0)
        pkt.AddHeader(src)
        parsed = ns.openoptics.OpenOpticsSourceRouteHeader()
        pkt.RemoveHeader(parsed)
        self.assertEqual(parsed.GetHopCount(), 2)
        self.assertEqual(parsed.GetCurrentIdx(), 1)
        self.assertEqual(parsed.GetHopAt(1).send_port_or_node, 1)


@skip_if_no_ns3
class SourceRoutingDispatchTests(unittest.TestCase):
    """Table-entry dispatch: ensure Ns3Backend forwards SR + cal entries
    to the C++ TorApp instead of raising NotImplementedError (as M1 did)."""

    def setUp(self):
        os.environ["OPENOPTICS_NS3_NO_PAUSE"] = "1"
        os.environ["OPENOPTICS_NS3_NO_REPORT"] = "1"

    def tearDown(self):
        os.environ.pop("OPENOPTICS_NS3_NO_REPORT", None)
        if ns3_available():
            from ns import ns
            ns.Simulator.Destroy()

    def test_source_routing_table_populated(self):
        from openoptics import OpticalTopo, OpticalRouting, Toolbox
        from openoptics.backends.ns3.backend import Ns3Backend

        nb_node = 4
        backend = Ns3Backend()
        with patch("openoptics.Toolbox.create_backend", return_value=backend):
            net = Toolbox.BaseNetwork(
                name="dispatch", backend="ns3", nb_node=nb_node,
                time_slice_duration_us=10_000, guardband_ms=0,
                use_webserver=False, simulation_stop_s=0.05,
            )
            net.deploy_topo(OpticalTopo.round_robin(nb_node=nb_node))
            paths = OpticalRouting.routing_direct(net.get_topo())
            net.deploy_routing(paths, routing_mode="Source")

        for tor_id in range(nb_node):
            app = backend._tor_apps[tor_id]
            # Every ToR has per-destination × per-slice source-routing
            # entries (3 other ToRs × 3 arrival slices = 9).
            self.assertEqual(
                app.GetSourceRoutingEntryCount(), 9,
                f"tor{tor_id} expected 9 SR entries")
            # cal_port_slice_to_node is also installed on every ToR —
            # used by VLB's node-type sentinel even when the current
            # example doesn't exercise it.
            self.assertEqual(app.GetCalPortSliceToNodeEntryCount(), 9)
            # And per_hop_routing must NOT be populated in Source mode.
            self.assertEqual(app.GetPerHopEntryCount(), 0)

    def test_cal_port_slice_to_node_populated_in_per_hop_mode(self):
        """`cal_port_slice_to_node` is still installed by Toolbox.setup_nodes
        regardless of routing_mode; we now store it (previously ignored)
        so it's ready for VLB to consult."""
        from openoptics import OpticalTopo, OpticalRouting, Toolbox
        from openoptics.backends.ns3.backend import Ns3Backend

        nb_node = 4
        backend = Ns3Backend()
        with patch("openoptics.Toolbox.create_backend", return_value=backend):
            net = Toolbox.BaseNetwork(
                name="cal", backend="ns3", nb_node=nb_node,
                time_slice_duration_us=10_000, guardband_ms=0,
                use_webserver=False, simulation_stop_s=0.05,
            )
            net.deploy_topo(OpticalTopo.round_robin(nb_node=nb_node))
            net.deploy_routing(
                OpticalRouting.routing_direct(net.get_topo()),
                routing_mode="Per-hop",
            )

        for tor_id in range(nb_node):
            app = backend._tor_apps[tor_id]
            self.assertEqual(app.GetCalPortSliceToNodeEntryCount(), 9)

    def test_admission_control_with_source_routing_warns(self):
        """admission_control=True is per-hop only; combining it with
        routing_mode="Source" should emit a one-shot RuntimeWarning rather
        than silently no-op'ing on the SR fast path."""
        import warnings as _warnings
        from openoptics import OpticalTopo, OpticalRouting, Toolbox
        from openoptics.backends.ns3.backend import Ns3Backend

        nb_node = 4
        backend = Ns3Backend()
        with patch("openoptics.Toolbox.create_backend", return_value=backend):
            net = Toolbox.BaseNetwork(
                name="adm-sr", backend="ns3", nb_node=nb_node,
                time_slice_duration_us=10_000, guardband_ms=0,
                use_webserver=False, simulation_stop_s=0.05,
                admission_control=True,
            )
            net.deploy_topo(OpticalTopo.round_robin(nb_node=nb_node))
            paths = OpticalRouting.routing_direct(net.get_topo())
            with _warnings.catch_warnings(record=True) as caught:
                _warnings.simplefilter("always")
                net.deploy_routing(paths, routing_mode="Source")

        adm_warnings = [
            w for w in caught
            if issubclass(w.category, RuntimeWarning)
            and "admission_control" in str(w.message)
        ]
        # Must fire exactly once — the dispatch site is hit per-entry, but
        # the guard is one-shot.
        self.assertEqual(len(adm_warnings), 1, [str(w.message) for w in caught])

    def test_admission_control_with_per_hop_routing_silent(self):
        """No SR warning when admission_control=True is paired with the
        per-hop forwarding path it actually applies to."""
        import warnings as _warnings
        from openoptics import OpticalTopo, OpticalRouting, Toolbox
        from openoptics.backends.ns3.backend import Ns3Backend

        nb_node = 4
        backend = Ns3Backend()
        with patch("openoptics.Toolbox.create_backend", return_value=backend):
            net = Toolbox.BaseNetwork(
                name="adm-perhop", backend="ns3", nb_node=nb_node,
                time_slice_duration_us=10_000, guardband_ms=0,
                use_webserver=False, simulation_stop_s=0.05,
                admission_control=True,
            )
            net.deploy_topo(OpticalTopo.round_robin(nb_node=nb_node))
            paths = OpticalRouting.routing_direct(net.get_topo())
            with _warnings.catch_warnings(record=True) as caught:
                _warnings.simplefilter("always")
                net.deploy_routing(paths, routing_mode="Per-hop")

        adm_warnings = [
            w for w in caught
            if issubclass(w.category, RuntimeWarning)
            and "admission_control" in str(w.message)
        ]
        self.assertEqual(len(adm_warnings), 0, [str(w.message) for w in caught])


@skip_if_no_ns3
class SourceRoutingEndToEndTests(unittest.TestCase):
    """Full-pipeline tests mirroring the four new examples."""

    def setUp(self):
        os.environ["OPENOPTICS_NS3_NO_PAUSE"] = "1"
        os.environ["OPENOPTICS_NS3_NO_REPORT"] = "1"

    def tearDown(self):
        os.environ.pop("OPENOPTICS_NS3_NO_REPORT", None)
        if ns3_available():
            from ns import ns
            ns.Simulator.Destroy()

    def _run(self, *, nb_node, topo_fn, routing_fn, src, dst,
             num_packets=5, simulation_stop_s=0.5):
        from openoptics import OpticalTopo, Toolbox
        from openoptics.backends.ns3.backend import Ns3Backend

        backend = Ns3Backend()
        with patch("openoptics.Toolbox.create_backend", return_value=backend):
            net = Toolbox.BaseNetwork(
                name="sr_e2e", backend="ns3", nb_node=nb_node, nb_link=1,
                time_slice_duration_us=10_000, guardband_ms=0,
                use_webserver=False,
                simulation_stop_s=simulation_stop_s,
            )
            net.deploy_topo(topo_fn(net))
            paths = routing_fn(net)
            net.deploy_routing(paths, routing_mode="Source")
            net.udp_traffic().echo(
                src, dst, start_s=0.02,
                stop_s=simulation_stop_s - 0.05,
                num_packets=num_packets, interval_s=0.03,
            ).install()
            net.start()
        return backend

    def test_direct_source_1hop_delivers(self):
        from openoptics import OpticalTopo, OpticalRouting
        backend = self._run(
            nb_node=4,
            topo_fn=lambda net: OpticalTopo.round_robin(nb_node=4),
            routing_fn=lambda net: OpticalRouting.routing_direct(net.get_topo()),
            src=0, dst=1, num_packets=5,
        )
        self.assertEqual(backend._tor_apps[0].GetIngressFromHostCount(), 5)
        self.assertEqual(backend._tor_apps[1].GetDeliveredToHostCount(), 5)
        # Echo reply also went through.
        self.assertEqual(backend._tor_apps[0].GetDeliveredToHostCount(), 5)
        # No drops.
        self.assertEqual(backend._ocs_app.GetDropCount(), 0)
        for tor_id in range(4):
            self.assertEqual(backend._tor_apps[tor_id].GetDropCount(), 0)
        # No intermediate ToRs relayed for 1-hop paths.
        for tor_id in (2, 3):
            self.assertEqual(
                backend._tor_apps[tor_id].GetIngressFromUplinkCount(), 0)

    def test_hoho_source_multi_hop_delivers(self):
        from openoptics import OpticalTopo, OpticalRouting

        def _topo(net):
            return OpticalTopo.opera(nb_node=4, nb_link=1)

        def _routing(net):
            return OpticalRouting.routing_hoho(net.get_topo())

        backend = self._run(
            nb_node=4, topo_fn=_topo, routing_fn=_routing,
            src=0, dst=2, num_packets=5, simulation_stop_s=0.7,
        )
        self.assertEqual(backend._tor_apps[0].GetIngressFromHostCount(), 5)
        self.assertEqual(backend._tor_apps[2].GetDeliveredToHostCount(), 5)
        # HoHo picks a 2-hop path for (0,2) → exactly one intermediate
        # (tor1 or tor3) relays the forward direction and one relays
        # the reply. In the opera(4,1) schedule the forward and reply
        # intermediates may be the same or different; all that matters
        # is that the forwards are accounted for.
        intermediate_relays = sum(
            int(backend._tor_apps[i].GetIngressFromUplinkCount())
            for i in (1, 3)
        )
        self.assertGreaterEqual(
            intermediate_relays, 1,
            "at least one intermediate ToR should have relayed SR traffic")
        self.assertEqual(backend._ocs_app.GetDropCount(), 0)

    def test_vlb_deterministic_uses_node_type_hop(self):
        """routing_vlb(random=False) produces 2-hop source-routes where
        the second hop is a node-type sentinel. The intermediate ToR
        must resolve it via cal_port_slice_to_node and forward."""
        from openoptics import OpticalRouting, OpticalTopo

        def _topo(net):
            return OpticalTopo.round_robin(nb_node=4)

        def _routing(net):
            return OpticalRouting.routing_vlb(net.get_topo(), net.tor_ocs_ports)

        backend = self._run(
            nb_node=4, topo_fn=_topo, routing_fn=_routing,
            src=0, dst=2, num_packets=5,
        )
        # tor0 source-routes; tor2 is destination.
        self.assertEqual(backend._tor_apps[0].GetIngressFromHostCount(), 5)
        self.assertEqual(backend._tor_apps[2].GetDeliveredToHostCount(), 5)
        # No drops — cal_port_slice_to_node successfully resolved the
        # node-type second hop at every intermediate.
        for tor_id in range(4):
            self.assertEqual(
                backend._tor_apps[tor_id].GetDropCount(), 0,
                f"tor{tor_id} had drops — node-type resolution likely failed")

    def _find_ocs_peer_of_tor(self, backend, tor_id):
        """Return the OCS-side NetDevice wired to `tor_id`'s first uplink.

        Send()-ing from this device enters the tor's uplink channel,
        firing ReceiveFromUplink on the TorApp under test.
        """
        tor_node = backend._tor_nodes[tor_id]
        for di in range(tor_node.GetNDevices()):
            dev = tor_node.GetDevice(di)
            # cppyy returns a null Ptr<Channel> (not Python None) for
            # loopback devices; `bool(chan)` maps to Ptr::operator bool.
            chan = dev.GetChannel()
            if not chan:
                continue
            if chan.GetNDevices() != 2:
                continue
            peer = (chan.GetDevice(0)
                    if chan.GetDevice(0) != dev else chan.GetDevice(1))
            if peer.GetNode() == backend._ocs_node:
                return peer
        return None

    @staticmethod
    def _build_sr_packet(ns, dst_node, arrival_ts, hops, current_idx):
        """Build an [OpenOpticsHeader(SR)][SR] wrapped packet from the
        given hop list."""
        import cppyy
        HopT = "ns3::openoptics::OpenOpticsSourceRouteHeader::Hop"
        hop_vec = cppyy.gbl.std.vector[HopT]()
        for cn, ts, port in hops:
            h = ns.openoptics.OpenOpticsSourceRouteHeader.Hop()
            h.cur_node = cn
            h.send_ts = ts
            h.send_port_or_node = port
            hop_vec.push_back(h)
        sr = ns.openoptics.OpenOpticsSourceRouteHeader(hop_vec)
        sr.SetCurrentIdx(current_idx)
        pkt = ns.Create["ns3::Packet"](32)
        pkt.AddHeader(sr)
        oo = ns.openoptics.OpenOpticsHeader(dst_node, arrival_ts)
        oo.SetMode(ns.openoptics.OpenOpticsHeader.kSourceRouted)
        pkt.AddHeader(oo)
        return pkt

    def _run_wrong_tor_cur_node(self, verify_sr_cur_node):
        """Shared harness for the two cur_node tests. Injects a forged SR
        packet at tor0 whose hops[0].cur_node == 99. Returns the per-ToR
        (drop, forwarded) deltas so the tests can assert the flag's effect.
        """
        from ns import ns
        from openoptics.backends.ns3.backend import Ns3Backend
        from openoptics import OpticalTopo, OpticalRouting, Toolbox

        nb_node = 4
        backend = Ns3Backend()
        kwargs = {}
        if verify_sr_cur_node:
            kwargs["verify_sr_cur_node"] = True
        with patch("openoptics.Toolbox.create_backend", return_value=backend):
            net = Toolbox.BaseNetwork(
                name="verify_flag", backend="ns3", nb_node=nb_node,
                time_slice_duration_us=10_000, guardband_ms=0,
                use_webserver=False, simulation_stop_s=0.05,
                **kwargs,
            )
            net.deploy_topo(OpticalTopo.round_robin(nb_node=nb_node))
            paths = OpticalRouting.routing_direct(net.get_topo())
            net.deploy_routing(paths, routing_mode="Source")

            peer_dev = self._find_ocs_peer_of_tor(backend, 0)
            if peer_dev is None:
                self.skipTest("couldn't locate tor0 uplink peer dev")

            # 2-hop SR packet, current_idx=0, hops[0].cur_node=99 (bogus).
            # With the gate off, ResolveHop runs on the port-type hop and
            # the packet is forwarded to send_port=0. With the gate on,
            # the cur_node mismatch trips the drop.
            pkt = self._build_sr_packet(
                ns, dst_node=2, arrival_ts=0,
                hops=((99, 0, 0), (1, 0, 0)), current_idx=0,
            )

            drops_before = int(backend._tor_apps[0].GetDropCount())
            fwd_before = int(backend._tor_apps[0].GetForwardedCount())

            peer_dev.Send(pkt, peer_dev.GetBroadcast(), 0x0800)
            ns.Simulator.Stop(ns.MilliSeconds(5))
            ns.Simulator.Run()

        return (
            int(backend._tor_apps[0].GetDropCount()) - drops_before,
            int(backend._tor_apps[0].GetForwardedCount()) - fwd_before,
        )

    def test_verify_sr_cur_node_default_passes_wrong_tor(self):
        """Control: with the flag off (default), a transit SR packet
        whose hop.cur_node disagrees with the local ToR id still
        resolves and forwards. (The packet may later be dropped at a
        downstream ToR whose arrive_at_dst doesn't cover the forged
        dst_node — that's expected and not what this test checks.)"""
        _, fwd = self._run_wrong_tor_cur_node(verify_sr_cur_node=False)
        self.assertGreaterEqual(
            fwd, 1,
            "flag off should forward via ResolveHop despite bogus cur_node")

    def test_verify_sr_cur_node_enabled_drops_wrong_tor(self):
        """With verify_sr_cur_node=True, a transit SR hop whose
        cur_node disagrees with the local ToR id is dropped before
        ResolveHop runs — no forwarding, one drop."""
        drops, fwd = self._run_wrong_tor_cur_node(verify_sr_cur_node=True)
        self.assertEqual(fwd, 0, "flag on should not forward")
        self.assertGreaterEqual(
            drops, 1, "flag on should drop on cur_node mismatch")

    def test_vlb_random_sentinel_dispatches(self):
        """routing_vlb(random=True) emits a random-port first hop:
        (cur_node=255, send_ts=255, send_port_or_node=255). The ingress
        ToR picks an uplink via UniformRandomVariable and sends in the
        current slice."""
        from openoptics import OpticalRouting, OpticalTopo

        def _topo(net):
            return OpticalTopo.round_robin(nb_node=4)

        def _routing(net):
            return OpticalRouting.routing_vlb(
                net.get_topo(), net.tor_ocs_ports, random=True,
            )

        backend = self._run(
            nb_node=4, topo_fn=_topo, routing_fn=_routing,
            src=0, dst=2, num_packets=5,
        )
        # With nb_link=1 the "random" draw has only one option (uplink
        # 0), but the code path is still exercised. Drop count must stay
        # zero and the destination must receive all packets.
        self.assertEqual(backend._tor_apps[0].GetIngressFromHostCount(), 5)
        self.assertEqual(backend._tor_apps[2].GetDeliveredToHostCount(), 5)
        for tor_id in range(4):
            self.assertEqual(
                backend._tor_apps[tor_id].GetDropCount(), 0,
                f"tor{tor_id} had drops under VLB random=True")


if __name__ == "__main__":
    unittest.main()
