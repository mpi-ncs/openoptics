# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# License: Creative Commons NC BY SA 4.0
#
# Deterministic single-packet tests.
#
# ns-3 is fully deterministic, so a packet injected at a specific simulation
# time follows a predictable path and accumulates a predictable delay. These
# tests lock in that behaviour against analytically computed expectations:
#
#   * per-ToR counters tell us which nodes the packet touched (path);
#   * FlowMonitor's min/max delay tell us how long it spent on that path,
#     including any calendar-queue wait (queuing correctness).
#
# Three scenarios cover the main paths through the M1 pipeline:
#
#   (a) same-slice direct send: inject when the target circuit is already
#       active -> no queuing, delay = pure wire baseline.
#   (b) early injection on direct path: inject one slice before the target
#       circuit is active -> calendar queue holds the packet for exactly
#       one slice_duration.
#   (c) HoHo multi-hop (opera/4,1): the packet must traverse an
#       intermediate ToR; counters confirm the intermediate was used and
#       the destination delivered to its host.

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.ns3_helpers import skip_if_no_ns3, ns3_available


@skip_if_no_ns3
class DeterministicPathTests(unittest.TestCase):
    """Single-packet injection; verify counters and delays analytically."""

    # Keep one ns-3 configuration across tests so the analytical formulas
    # stay simple. Defaults chosen so the calendar-queue wait dominates and
    # baselines stay in the tens of microseconds.
    SLICE_US = 10_000           # 10 ms per slice
    SIM_STOP_S = 0.5            # room for slice waits + echo replies
    PACKET_BYTES = 64           # small so transmission time is negligible
    HOST_DELAY_US = 1
    OCS_DELAY_US = 1
    OCS_LINK_BW_GBPS = 1        # 1 Gbps — tx time ≈ 1 us for our packet size

    def setUp(self):
        # Prevent run() from blocking on input(); silence the stdout report.
        os.environ["OPENOPTICS_NS3_NO_PAUSE"] = "1"
        os.environ["OPENOPTICS_NS3_NO_REPORT"] = "1"

    def tearDown(self):
        os.environ.pop("OPENOPTICS_NS3_NO_REPORT", None)
        if ns3_available():
            from ns import ns
            ns.Simulator.Destroy()

    # --- helpers ------------------------------------------------------

    def _run(self, *, nb_node, topo, routing, src, dst, inject_at_s):
        """Build the topology, inject a single packet at the exact sim
        time, run to completion, return the (backend, net) pair."""
        from openoptics import OpticalTopo, OpticalRouting, Toolbox
        from openoptics.backends.ns3.backend import Ns3Backend

        backend = Ns3Backend()
        with patch("openoptics.Toolbox.create_backend", return_value=backend):
            net = Toolbox.BaseNetwork(
                name="det", backend="ns3", nb_node=nb_node, nb_link=1,
                time_slice_duration_us=self.SLICE_US, guardband_ms=0,
                ocs_tor_link_bw_gbps=self.OCS_LINK_BW_GBPS,
                use_webserver=False,
                simulation_stop_s=self.SIM_STOP_S,
                host_link_delay_us=self.HOST_DELAY_US,
                ocs_link_delay_us=self.OCS_DELAY_US,
            )
            if topo == "round_robin":
                circuits = OpticalTopo.round_robin(nb_node=nb_node)
            elif topo == "opera":
                circuits = OpticalTopo.opera(nb_node=nb_node, nb_link=1)
            else:
                raise ValueError(topo)
            net.deploy_topo(circuits)

            if routing == "direct":
                paths = OpticalRouting.routing_direct(net.get_topo())
            elif routing == "hoho":
                paths = OpticalRouting.routing_hoho(net.get_topo())
            else:
                raise ValueError(routing)
            net.deploy_routing(paths, routing_mode="Per-hop")

            # Inject one packet. `interval_s` is a no-op for num_packets=1
            # but setting it comfortably larger than the window avoids any
            # future multi-packet surprises.
            net.udp_traffic().echo(
                src, dst,
                start_s=inject_at_s,
                stop_s=self.SIM_STOP_S - 0.01,
                num_packets=1,
                interval_s=1.0,
                packet_size_bytes=self.PACKET_BYTES,
            ).install()
            net.start()
        return backend, net

    def _flow_table(self, backend):
        """Return {(src_ip, dst_ip): (tx, rx, min_ns, max_ns)}."""
        ns = backend._ns
        backend._flow_monitor.CheckForLostPackets()
        classifier = ns.DynamicCast["ns3::Ipv4FlowClassifier"](
            backend._flow_helper.GetClassifier()
        )
        out = {}
        for flow_id, s in backend._flow_monitor.GetFlowStats():
            t = classifier.FindFlow(flow_id)
            out[(str(t.sourceAddress), str(t.destinationAddress))] = (
                int(s.txPackets), int(s.rxPackets),
                int(s.minDelay.GetNanoSeconds()),
                int(s.maxDelay.GetNanoSeconds()),
            )
        return out

    # --- (a) same-slice direct send -----------------------------------

    def test_direct_same_slice_has_no_queue_wait(self):
        """round_robin(4) places the (0,1) circuit in slice 2. Injecting
        1 μs into slice 2 means arrival_ts == send_ts, the same-slice send
        path fires, and there is no calendar-queue wait. Observed end-to-
        end delay must be a small fraction of a slice duration."""
        # Slice 2 starts at t = 2 * slice_duration = 20 ms. Offset by 1 μs
        # so we're unambiguously inside the slice (not exactly on the
        # boundary where OnSliceBoundary and the host send would race).
        inject_at_s = 2 * self.SLICE_US * 1e-6 + 1e-6
        backend, _ = self._run(
            nb_node=4, topo="round_robin", routing="direct",
            src=0, dst=1, inject_at_s=inject_at_s,
        )

        # Path: h0 → tor0 → OCS → tor1 → h1. Echo reply returns the same
        # way (tor1 → OCS → tor0 → h0), so tor0/tor1 each see exactly one
        # ingress-from-host (their own host) and one ingress-from-uplink
        # (from the echo direction).
        self.assertEqual(backend._tor_apps[0].GetIngressFromHostCount(), 1)
        self.assertEqual(backend._tor_apps[0].GetForwardedCount(), 1)
        self.assertEqual(backend._tor_apps[0].GetIngressFromUplinkCount(), 1)
        self.assertEqual(backend._tor_apps[0].GetDeliveredToHostCount(), 1)
        self.assertEqual(backend._tor_apps[1].GetIngressFromHostCount(), 1)
        self.assertEqual(backend._tor_apps[1].GetForwardedCount(), 1)
        self.assertEqual(backend._tor_apps[1].GetIngressFromUplinkCount(), 1)
        self.assertEqual(backend._tor_apps[1].GetDeliveredToHostCount(), 1)
        for idle in (2, 3):
            self.assertEqual(
                backend._tor_apps[idle].GetIngressFromHostCount(), 0,
                f"tor{idle} should have seen no host traffic")
            self.assertEqual(
                backend._tor_apps[idle].GetIngressFromUplinkCount(), 0,
                f"tor{idle} should have seen no uplink traffic")
        self.assertEqual(backend._ocs_app.GetDropCount(), 0)

        # One-way delay ≈ 2 × host_delay + 2 × ocs_delay (+ a few μs of
        # per-hop transmission at 1 Gbps for a 64-byte packet). Put a
        # generous ceiling an order of magnitude below one slice.
        flow = self._flow_table(backend)
        fwd_min_ns = flow[("10.0.0.1", "10.0.1.1")][2]
        self.assertLess(
            fwd_min_ns, self.SLICE_US * 100,   # < 1 ms in ns
            f"same-slice delay should be sub-millisecond, got {fwd_min_ns} ns",
        )

    # --- (b) direct send with one-slice queue wait --------------------

    def test_direct_one_slice_early_waits_exactly_one_slice(self):
        """Inject during slice 1. routing_direct's per-hop entry at tor0
        still says send_ts=2 (the only slice where the (0,1) circuit is
        active), so the packet parks in CalendarQueue[2] and waits one
        full slice_duration before OnSliceBoundary drains it."""
        inject_at_s = 1 * self.SLICE_US * 1e-6 + 1e-6   # 1 μs into slice 1
        backend, _ = self._run(
            nb_node=4, topo="round_robin", routing="direct",
            src=0, dst=1, inject_at_s=inject_at_s,
        )

        # Same delivery pattern as (a) — path is identical; only the
        # calendar-queue dwell time differs.
        self.assertEqual(backend._tor_apps[0].GetIngressFromHostCount(), 1)
        self.assertEqual(backend._tor_apps[1].GetDeliveredToHostCount(), 1)
        self.assertEqual(backend._tor_apps[0].GetDeliveredToHostCount(), 1,
                         "echo reply should come back to tor0's host")
        self.assertEqual(backend._ocs_app.GetDropCount(), 0)
        for tor_id in range(4):
            self.assertEqual(backend._tor_apps[tor_id].GetDropCount(), 0)

        # Expected delay = wait_for_send_slice + baseline wire delay.
        # arrival_ts=1, send_ts=2 → wait 1 slice = 10 ms = 10 * 1e6 ns.
        # Wire baseline is ≲ 1 ms total, so we bound [0.99, 1.10] slice.
        flow = self._flow_table(backend)
        fwd_min_ns = flow[("10.0.0.1", "10.0.1.1")][2]
        slice_ns = self.SLICE_US * 1000
        self.assertGreaterEqual(
            fwd_min_ns, int(slice_ns * 0.99),
            f"expected ≥ ~1 slice wait (~{slice_ns} ns), got {fwd_min_ns}")
        self.assertLessEqual(
            fwd_min_ns, int(slice_ns * 1.10),
            f"expected ≲ 1 slice + wire baseline, got {fwd_min_ns}")

    # --- (c) HoHo 2-hop path in opera(4,1) ----------------------------

    def test_hoho_multi_hop_uses_intermediate_tor(self):
        """opera(4,1) has only 4*2=8 directed edges across 4 slices; not
        every (src,dst) pair has a direct circuit in any slice, so
        routing_hoho(max_hop=2) picks a 2-hop path for those. We pick
        (0, 2) — empirically 2-hop under opera(4,1) — and verify via
        per-ToR counters that exactly one intermediate ToR relayed the
        packet while the destination delivered it."""
        inject_at_s = 0.02
        backend, _ = self._run(
            nb_node=4, topo="opera", routing="hoho",
            src=0, dst=2, inject_at_s=inject_at_s,
        )

        # Source and destination counters are tight:
        self.assertEqual(backend._tor_apps[0].GetIngressFromHostCount(), 1,
                         "tor0 should have received one packet from h0")
        self.assertEqual(backend._tor_apps[2].GetDeliveredToHostCount(), 1,
                         "tor2 should have delivered one packet to h2")
        # Echo reply traveled back:
        self.assertEqual(backend._tor_apps[2].GetIngressFromHostCount(), 1)
        self.assertEqual(backend._tor_apps[0].GetDeliveredToHostCount(), 1)

        # Across the possible intermediates (tor1, tor3) the total
        # ingress-from-uplink should equal the number of hops-through
        # performed in each direction. For a 2-hop forward path and a
        # 2-hop return path (opera/HoHo is not guaranteed symmetric), the
        # two directions consume one intermediate hop each: sum == 2.
        # If HoHo finds a 1-hop direct path for either direction, the
        # sum drops to 1.
        intermediate_relays = sum(
            int(backend._tor_apps[i].GetIngressFromUplinkCount())
            for i in (1, 3)
        )
        intermediate_forwards = sum(
            int(backend._tor_apps[i].GetForwardedCount())
            for i in (1, 3)
        )
        # At least one hop-through (the interesting scenario); every
        # packet that arrived on an intermediate's uplink must have been
        # forwarded (not delivered to its host, not dropped).
        self.assertGreaterEqual(
            intermediate_relays, 1,
            "expected at least one intermediate-hop relay in HoHo path")
        self.assertEqual(
            intermediate_forwards, intermediate_relays,
            "intermediates should forward every packet they receive on "
            "uplink — none should have been dropped or delivered locally")

        # Zero drops overall.
        self.assertEqual(backend._ocs_app.GetDropCount(), 0)
        for tor_id in range(4):
            self.assertEqual(backend._tor_apps[tor_id].GetDropCount(), 0)

        # FlowMonitor: both directions got through.
        flow = self._flow_table(backend)
        fwd = flow[("10.0.0.1", "10.0.2.1")]
        rev = flow[("10.0.2.1", "10.0.0.1")]
        self.assertEqual(fwd[:2], (1, 1))  # tx=rx=1
        self.assertEqual(rev[:2], (1, 1))


if __name__ == "__main__":
    unittest.main()
