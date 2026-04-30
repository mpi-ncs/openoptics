# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# License: Creative Commons NC BY SA 4.0
#
# ToR + CalendarQueue behaviour tests.

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import unittest

from tests.ns3_helpers import skip_if_no_ns3, ns3_available


@skip_if_no_ns3
class CalendarQueueTests(unittest.TestCase):
    """Unit tests for the templated C++ CalendarQueue<T>."""

    def test_enqueue_dequeue(self):
        from ns import ns
        cq = ns.openoptics.CalendarQueue["int"](4)
        self.assertTrue(cq.Enqueue(2, 100, 7))
        self.assertTrue(cq.Enqueue(2, 200, 7))
        self.assertTrue(cq.Enqueue(2, 300, 7))
        self.assertEqual(cq.Depth(2), 3)
        self.assertEqual(cq.Depth(0), 0)

    def test_no_packet_capacity_limit(self):
        from ns import ns
        cq = ns.openoptics.CalendarQueue["int"](1)
        for i in range(20):
            self.assertTrue(cq.Enqueue(0, i, 0))
        self.assertEqual(cq.Depth(0), 20)
        self.assertEqual(cq.GetDropCount(), 0)

    def test_out_of_range_slice(self):
        from ns import ns
        cq = ns.openoptics.CalendarQueue["int"](2)
        self.assertFalse(cq.Enqueue(99, 42, 0))
        self.assertEqual(cq.GetDropCount(), 1)


@skip_if_no_ns3
class TorAppBehaviourTests(unittest.TestCase):
    """Hand-crafted table entries exercised against TorApp."""

    def tearDown(self):
        if ns3_available():
            from ns import ns
            ns.Simulator.Destroy()

    def _make_tor(self, tor_id=0, nb_slices=3, slice_us=10_000, nb_uplinks=1,
                  cq_buffer_bytes=1_048_576):
        """Build a node with TorApp + 1 host-facing + N uplink P2P devices.

        Returns (ns, tor_app, host_peer_dev, [uplink_peer_devs]).
        """
        from ns import ns
        tor_node = ns.CreateObject["ns3::Node"]()
        internet = ns.InternetStackHelper()
        internet.Install(tor_node)
        tor_node.GetObject[ns.Ipv4]().SetAttribute(
            "IpForward", ns.BooleanValue(False)
        )

        app = ns.CreateObject["ns3::openoptics::TorApp"]()
        tor_node.AddApplication(app)
        app.SetTorId(tor_id)
        app.SetSliceDurationUs(slice_us)
        app.SetNumSlices(nb_slices)
        app.SetCalendarQueueBufferCapacityBytes(cq_buffer_bytes)
        # Default uplink rate matches the p2p link below (1 Gbps); tests
        # that exercise admission rejection override this with a smaller
        # value via app.SetUplinkLinkRateBps(...) after construction.
        app.SetUplinkLinkRateBps(1_000_000_000)
        app.SetStartTime(ns.Seconds(0.0))

        p2p = ns.PointToPointHelper()
        p2p.SetDeviceAttribute("DataRate", ns.StringValue("1Gbps"))
        p2p.SetChannelAttribute("Delay", ns.TimeValue(ns.MicroSeconds(1)))

        # Host-facing link
        host_node = ns.CreateObject["ns3::Node"]()
        internet.Install(host_node)
        host_devs = p2p.Install(tor_node, host_node)
        app.SetHostDevice(host_devs.Get(0))
        addr = ns.Ipv4AddressHelper()
        addr.SetBase(ns.Ipv4Address("10.9.0.0"), ns.Ipv4Mask("255.255.255.0"))
        addr.Assign(host_devs)
        host_peer = host_devs.Get(1)

        # Uplinks (no IP)
        uplink_peers = []
        for _ in range(nb_uplinks):
            peer_node = ns.CreateObject["ns3::Node"]()
            devs = p2p.Install(tor_node, peer_node)
            app.AddUplinkDevice(devs.Get(0))
            uplink_peers.append(devs.Get(1))

        return ns, app, host_peer, uplink_peers

    def test_tor_delivers_at_destination(self):
        """Uplink ingress with matching OpenOpticsHeader.dst_node → host."""
        ns, app, host_peer, uplinks = self._make_tor(tor_id=0)
        app.AddArriveAtDst(dst_node=0, host_port=0)

        # Build a packet with OpenOpticsHeader(dst=0, ats=0).
        pkt = ns.Create["ns3::Packet"](64)
        hdr = ns.openoptics.OpenOpticsHeader(0, 0)
        pkt.AddHeader(hdr)
        uplinks[0].Send(pkt, uplinks[0].GetBroadcast(), 0x0800)

        ns.Simulator.Stop(ns.MilliSeconds(1))
        ns.Simulator.Run()

        self.assertEqual(app.GetIngressFromUplinkCount(), 1)
        self.assertEqual(app.GetDeliveredToHostCount(), 1)
        self.assertEqual(app.GetDropCount(), 0)

    def test_tor_misses_drop(self):
        """No routing table → drop."""
        ns, app, host_peer, uplinks = self._make_tor(tor_id=0)

        pkt = ns.Create["ns3::Packet"](64)
        hdr = ns.openoptics.OpenOpticsHeader(99, 0)  # dst_node=99: no table
        pkt.AddHeader(hdr)
        uplinks[0].Send(pkt, uplinks[0].GetBroadcast(), 0x0800)
        ns.Simulator.Stop(ns.MilliSeconds(1))
        ns.Simulator.Run()

        self.assertEqual(app.GetIngressFromUplinkCount(), 1)
        self.assertEqual(app.GetDeliveredToHostCount(), 0)
        self.assertEqual(app.GetDropCount(), 1)

    def test_tor_defers_to_send_slice(self):
        """Packet arrives in slice 0; entry says send_ts=2. CQ depth goes 0→1→0."""
        ns, app, host_peer, uplinks = self._make_tor(
            tor_id=0, nb_slices=3, slice_us=10_000, nb_uplinks=1,
        )
        # dst=1 reachable in slice 2 via uplink 0
        app.AddPerHopEntry(dst_node=1, arrival_ts=0, cur_node=0,
                           send_ts=2, send_port=0)

        pkt = ns.Create["ns3::Packet"](64)
        hdr = ns.openoptics.OpenOpticsHeader(1, 0)  # dst=1, arrival_ts=0
        pkt.AddHeader(hdr)
        # Arrive at t=0 (slice 0 active).
        uplinks[0].Send(pkt, uplinks[0].GetBroadcast(), 0x0800)

        # Run into slice 0 a bit — queue should have 1 packet at slot 2.
        ns.Simulator.Stop(ns.MicroSeconds(500))
        ns.Simulator.Run()
        self.assertEqual(app.GetQueueDepth(2), 1)
        self.assertEqual(app.GetForwardedCount(), 0)

        # Run past the slice-2 boundary (>=20ms) → drain fires.
        ns.Simulator.Stop(ns.MilliSeconds(25))
        ns.Simulator.Run()
        self.assertEqual(app.GetQueueDepth(2), 0)
        self.assertEqual(app.GetForwardedCount(), 1)
        self.assertEqual(app.GetDropCount(), 0)

    def test_cq_buffer_drops_by_total_queued_bytes(self):
        """The ToR calendar queue rejects when total buffered bytes exceed
        the configured byte limit, independent of packet count."""
        ns, app, host_peer, uplinks = self._make_tor(
            tor_id=0, nb_slices=4, slice_us=10_000, nb_uplinks=1,
        )
        payload_bytes = 1000
        pkt_bytes = (
            payload_bytes
            + int(ns.openoptics.OpenOpticsHeader(1, 0).GetSerializedSize())
        )
        app.SetCalendarQueueBufferCapacityBytes(2 * pkt_bytes)
        app.AddPerHopEntry(dst_node=1, arrival_ts=0, cur_node=0,
                           send_ts=2, send_port=0)

        for _ in range(3):
            pkt = ns.Create["ns3::Packet"](payload_bytes)
            hdr = ns.openoptics.OpenOpticsHeader(1, 0)
            pkt.AddHeader(hdr)
            uplinks[0].Send(pkt, uplinks[0].GetBroadcast(), 0x0800)

        ns.Simulator.Stop(ns.MilliSeconds(1))
        ns.Simulator.Run()

        self.assertEqual(app.GetTotalQueueDepth(), 2)
        self.assertEqual(app.GetTotalQueueBytes(), 2 * pkt_bytes)
        self.assertEqual(app.GetPeakQueueBytes(), 2 * pkt_bytes)
        self.assertEqual(app.GetDropCount(), 1)
        self.assertEqual(app.GetDropForwardCq(), 1)
        self.assertEqual(app.GetCalendarQueueDrops(), 1)

    def test_cq_buffer_limit_is_total_across_slices_and_uplinks(self):
        """Bytes split across slices/uplinks share one ToR-level limit."""
        ns, app, host_peer, uplinks = self._make_tor(
            tor_id=0, nb_slices=4, slice_us=10_000, nb_uplinks=2,
        )
        payload_bytes = 1000
        pkt_bytes = (
            payload_bytes
            + int(ns.openoptics.OpenOpticsHeader(1, 0).GetSerializedSize())
        )
        app.SetCalendarQueueBufferCapacityBytes(4 * pkt_bytes)
        app.AddPerHopEntry(dst_node=1, arrival_ts=0, cur_node=0,
                           send_ts=2, send_port=0)
        app.AddPerHopEntry(dst_node=2, arrival_ts=0, cur_node=0,
                           send_ts=3, send_port=1)

        def inject(dst):
            pkt = ns.Create["ns3::Packet"](payload_bytes)
            hdr = ns.openoptics.OpenOpticsHeader(dst, 0)
            pkt.AddHeader(hdr)
            uplinks[0].Send(pkt, uplinks[0].GetBroadcast(), 0x0800)

        for dst in (1, 1, 2, 2):
            inject(dst)

        ns.Simulator.Stop(ns.MilliSeconds(1))
        ns.Simulator.Run()

        self.assertEqual(app.GetDropCount(), 0)
        self.assertEqual(app.GetQueueDepth(2), 2)
        self.assertEqual(app.GetQueueDepth(3), 2)
        self.assertEqual(app.GetTotalQueueBytes(), 4 * pkt_bytes)

        inject(2)
        ns.Simulator.Stop(ns.MilliSeconds(2))
        ns.Simulator.Run()

        self.assertEqual(app.GetDropCount(), 1)
        self.assertEqual(app.GetDropForwardCq(), 1)
        self.assertEqual(app.GetTotalQueueDepth(), 4)
        self.assertEqual(app.GetTotalQueueBytes(), 4 * pkt_bytes)

    def test_slice_byte_budget_rejects_overflow(self):
        """Per-slice byte-budget admission control: oversubscribed tors
        record ovfl_drops instead of silently overflowing the link into
        the next slice (where the OCS would misroute packets)."""
        ns, app, host_peer, uplinks = self._make_tor(
            tor_id=0, nb_slices=4, slice_us=10_000, nb_uplinks=1,
        )
        # 20 Mbps link, 10 ms slice -> 25_000 bytes/slice.
        # Pick an oversized packet count that clearly exceeds the budget.
        app.SetUplinkLinkRateBps(20 * 1000 * 1000)
        app.AddPerHopEntry(dst_node=1, arrival_ts=0, cur_node=0,
                           send_ts=0, send_port=0)

        # Budget = 25000 B. Inject 10 packets of 5000 B each on the uplink;
        # ReceiveFromUplink re-stamps an 8-byte OpenOpticsHeader so each
        # packet is 5008 B on the send path. 4 fit (20032 B); the 5th
        # would cross 25000 B and gets rejected. Expect 4 forwarded, 6
        # overflow drops.
        for _ in range(10):
            pkt = ns.Create["ns3::Packet"](5000)
            hdr = ns.openoptics.OpenOpticsHeader(1, 0)
            pkt.AddHeader(hdr)
            uplinks[0].Send(pkt, uplinks[0].GetBroadcast(), 0x0800)

        ns.Simulator.Stop(ns.MilliSeconds(5))
        ns.Simulator.Run()
        self.assertEqual(app.GetForwardedCount(), 4,
                         "four 5008 B packets fit the 25000 B slice budget")
        self.assertEqual(app.GetSliceOverflowDrops(), 6,
                         "remaining 6 packets should be rejected")

    def test_guardband_reduces_byte_budget(self):
        """SetGuardbandUs(gb) shrinks the effective active window, which
        directly shrinks the per-slice byte budget. With a 10 ms / 20 Mbps
        slice, baseline budget is 25000 B; after gb=2 ms, budget is only
        20000 B. Three 5008 B packets fit (15024 B); the 4th (20032 B)
        would exceed the budget and must be rejected."""
        ns, app, host_peer, uplinks = self._make_tor(
            tor_id=0, nb_slices=4, slice_us=10_000, nb_uplinks=1,
        )
        app.SetUplinkLinkRateBps(20 * 1000 * 1000)
        app.SetGuardbandUs(2_000)   # 2 ms guardband -> effective 8000 us
        app.AddPerHopEntry(dst_node=1, arrival_ts=0, cur_node=0,
                           send_ts=0, send_port=0)

        for _ in range(5):
            pkt = ns.Create["ns3::Packet"](5000)
            hdr = ns.openoptics.OpenOpticsHeader(1, 0)
            pkt.AddHeader(hdr)
            uplinks[0].Send(pkt, uplinks[0].GetBroadcast(), 0x0800)

        ns.Simulator.Stop(ns.MilliSeconds(5))
        ns.Simulator.Run()
        self.assertEqual(app.GetForwardedCount(), 3,
                         "3x5008=15024 B fit under 20000 B budget")
        self.assertEqual(app.GetSliceOverflowDrops(), 2,
                         "remaining 2 packets exceed the budget")

    def test_uplink_prop_delay_reduces_byte_budget(self):
        """SetUplinkPropagationDelayUs(p) also shrinks the effective
        window. With a 10 ms / 20 Mbps slice and 1 ms prop, budget is
        22500 B. Four 5008 B packets (20032 B) fit; the 5th (25040 B)
        does not."""
        ns, app, host_peer, uplinks = self._make_tor(
            tor_id=0, nb_slices=4, slice_us=10_000, nb_uplinks=1,
        )
        app.SetUplinkLinkRateBps(20 * 1000 * 1000)
        app.SetUplinkPropagationDelayUs(1_000)  # -> effective 9000 us
        app.AddPerHopEntry(dst_node=1, arrival_ts=0, cur_node=0,
                           send_ts=0, send_port=0)

        for _ in range(5):
            pkt = ns.Create["ns3::Packet"](5000)
            hdr = ns.openoptics.OpenOpticsHeader(1, 0)
            pkt.AddHeader(hdr)
            uplinks[0].Send(pkt, uplinks[0].GetBroadcast(), 0x0800)

        ns.Simulator.Stop(ns.MilliSeconds(5))
        ns.Simulator.Run()
        self.assertEqual(app.GetForwardedCount(), 4)
        self.assertEqual(app.GetSliceOverflowDrops(), 1)

    def test_adm_mode_per_uplink_independent_admission(self):
        """ADM-mode admission planning is per-(slot, uplink). With
        nb_link=2 and queued bytes filling uplink 0's slot-2 capacity,
        a flow targeting uplink 1's slot 2 must not be ADM-rejected.

        Before the per-uplink m_cqBytesPerSlot fix, m_cqBytesPerSlice
        was a single 1D vector summed across all uplinks; AdmCheck for
        uplink 1 falsely saw uplink 0's queue depth and rejected.

        Setup uses send_ts=2 (not current slice) so packets enqueue at
        a future slot rather than taking the fast-path. The runtime
        byte budget (m_bytesThisSlice) is not yet per-uplink — fixed
        in subsequent steps and tracked separately."""
        ns, app, host_peer, uplinks = self._make_tor(
            tor_id=0, nb_slices=4, slice_us=10_000, nb_uplinks=2,
        )
        app.SetUplinkLinkRateBps(20 * 1000 * 1000)  # 25_000 B / slice
        app.SetAdmissionControl(True)
        # Both dsts route to slot 2 (future slot) on different uplinks.
        app.AddPerHopEntry(dst_node=1, arrival_ts=0, cur_node=0,
                           send_ts=2, send_port=0)
        app.AddPerHopEntry(dst_node=2, arrival_ts=0, cur_node=0,
                           send_ts=2, send_port=1)

        def inject(dst):
            pkt = ns.Create["ns3::Packet"](5000)
            hdr = ns.openoptics.OpenOpticsHeader(dst, 0)
            pkt.AddHeader(hdr)
            uplinks[0].Send(pkt, uplinks[0].GetBroadcast(), 0x0800)

        # 4 dst=1 packets fill uplink-0's slot-2 queue to 20_032 B —
        # just under the 25_000 B per-uplink budget.
        for _ in range(4):
            inject(dst=1)
        # 1 dst=2 packet routes via uplink 1 at the same slot. Its
        # uplink's slot-2 queue is empty; per-uplink AdmCheck must
        # admit it.
        inject(dst=2)

        # Stop before slot-2 boundary (at t=20ms) so we measure ADM
        # planning, not runtime drain.
        ns.Simulator.Stop(ns.MilliSeconds(1))
        ns.Simulator.Run()

        self.assertEqual(app.GetDropAdmFail(), 0,
                         "uplink 1 must not be ADM-rejected by uplink "
                         "0's queue depth at the same slot")

    def test_byte_budget_resets_on_cycle_wrap(self):
        """Regression guard for cross-cycle stale state in admission.

        Originally written for the modulo-slice-id carryover bug in
        m_bytesThisSlice (since deleted): a counter that never reset
        for sparse same-slot flows. The runtime tracker is now
        m_linkFreeAt — an absolute simulator timestamp that can't carry
        stale state across cycles. This test still pins the property:
        traffic flowing on the same slot id across multiple cycles
        must not accumulate false rejections.

        Setup: 20 Mbps link, 10 ms slice. Inject 3 packets of 5008 B
        in cycle 0 mid-slice via the same-slice fast-path. Wait a full
        cycle. Inject 3 more in cycle 1 mid-slice. All 6 should pass.

        (With the historical m_bytesThisSlice carryover bug, cycle 1's
        counter would have been pre-loaded with cycle 0's bytes and
        the second + third cycle-1 packet would have been rejected.
        With the linkFreeAt design, no such state survives the cycle
        boundary, since linkFreeAt at end of cycle 0 is well past now
        when cycle 1's traffic arrives.)
        """
        ns, app, host_peer, uplinks = self._make_tor(
            tor_id=0, nb_slices=4, slice_us=10_000, nb_uplinks=1,
        )
        app.SetUplinkLinkRateBps(20 * 1000 * 1000)   # 25 KB / slice
        app.AddPerHopEntry(dst_node=1, arrival_ts=0, cur_node=0,
                           send_ts=0, send_port=0)

        def inject_3_packets():
            for _ in range(3):
                # Small packets so admission has comfortable headroom —
                # the test exercises cycle-wrap state, not edge-of-slot
                # admission.
                pkt = ns.Create["ns3::Packet"](1000)
                hdr = ns.openoptics.OpenOpticsHeader(1, 0)
                pkt.AddHeader(hdr)
                uplinks[0].Send(pkt, uplinks[0].GetBroadcast(), 0x0800)

        # Cycle 0, mid-slice 0.
        ns.Simulator.Stop(ns.MicroSeconds(2_000))
        ns.Simulator.Run()
        inject_3_packets()

        # Run past slices 1..3 with no traffic. linkFreeAt advanced into
        # mid-slot during cycle 0 and is left there; cycle 1 traffic at
        # t≈42 ms must observe it as "well in the past" and not let it
        # contaminate admission.
        ns.Simulator.Stop(ns.MicroSeconds(42_000))
        ns.Simulator.Run()

        # Cycle 1, mid-slice 0.
        inject_3_packets()
        ns.Simulator.Stop(ns.MicroSeconds(50_000))
        ns.Simulator.Run()

        self.assertEqual(app.GetForwardedCount(), 6,
                         "all 6 packets fit their respective per-cycle "
                         "windows; cycle wrap must not carry stale state")
        self.assertEqual(app.GetSliceOverflowDrops(), 0,
                         "no packet should be byte-budget rejected when "
                         "traffic is well within active-window capacity")

    def test_tor_same_slice_send_bypasses_queue(self):
        """Regression guard for the calendar-queue same-slice-wait bug.

        A packet arriving mid-slice with send_ts == current_slice must be
        transmitted immediately — NOT parked in CalendarQueue[current_slice]
        (whose OnSliceBoundary has already fired, which would force it to
        wait a full rotation). Symptom before the fix: Opera + HoHo
        multi-hop showed delays ≥ full calendar cycle.
        """
        ns, app, host_peer, uplinks = self._make_tor(
            tor_id=0, nb_slices=4, slice_us=10_000, nb_uplinks=1,
        )
        # dst=1 should leave in whatever slice the packet arrives in.
        app.AddPerHopEntry(dst_node=1, arrival_ts=0, cur_node=0,
                           send_ts=0, send_port=0)

        # Run far enough into slice 0 that its OnSliceBoundary (t=0) has
        # definitely fired already, then inject.
        ns.Simulator.Stop(ns.MicroSeconds(5_000))
        ns.Simulator.Run()
        pkt = ns.Create["ns3::Packet"](64)
        hdr = ns.openoptics.OpenOpticsHeader(1, 0)
        pkt.AddHeader(hdr)
        uplinks[0].Send(pkt, uplinks[0].GetBroadcast(), 0x0800)

        # Finish slice 0; nothing else should have scheduled the drain. If
        # the bug is present, forwarded stays at 0 until slice 0 comes
        # around again — i.e. after t=40ms. With the fix, forwarded flips
        # to 1 essentially immediately after the Send call returns.
        ns.Simulator.Stop(ns.MicroSeconds(6_000))
        ns.Simulator.Run()
        self.assertEqual(app.GetForwardedCount(), 1,
                         "same-slice packet should be transmitted "
                         "without waiting a full calendar cycle")
        self.assertEqual(app.GetQueueDepth(0), 0)
        self.assertEqual(app.GetDropCount(), 0)

    def test_late_in_slice_defers_one_cycle(self):
        """A same-slice packet that can't finish before the active-window
        deadline must not drop — it stays in the calendar queue and
        drains when this slot id recurs in the next cycle. Otherwise
        the OCS would mis-route it under the next slice's schedule.

        Setup: 1 Mbps link, 10 ms slice → effective_active_us = 10_000.
        A 5000 B packet serializes in 5000 * 8 / 1 Mbps = 40 ms — far
        longer than one slot. Inject mid-slot at t=2 ms with send_ts=0
        and expect: not transmitted in cycle 0 (would overrun every
        slot), but also not dropped — held in m_cq[0] for slot 0 until
        a future cycle where the deadline check would still fail.

        Easier framing: at any send time mid-slot, the packet's
        serialize >> remaining active window AND link is idle, so
        CanFinishInActiveWindow → false on the "late + idle" branch.
        Expected: 0 forwarded, 0 ovfl drops, queue depth still 1
        somewhere (it sits across cycles waiting for a window that
        never comes — OK, the test is about the disposition, not
        eventual delivery).
        """
        ns, app, host_peer, uplinks = self._make_tor(
            tor_id=0, nb_slices=4, slice_us=10_000, nb_uplinks=1,
        )
        # 1 Mbps so a 5000 B packet's serialize (40 ms) far exceeds any
        # 10 ms slot — every admission attempt fails on time, never on
        # link saturation (linkFreeAt stays at 0, link is idle).
        app.SetUplinkLinkRateBps(1 * 1000 * 1000)
        app.AddPerHopEntry(dst_node=1, arrival_ts=0, cur_node=0,
                           send_ts=0, send_port=0)

        ns.Simulator.Stop(ns.MicroSeconds(2_000))
        ns.Simulator.Run()
        pkt = ns.Create["ns3::Packet"](5000)
        hdr = ns.openoptics.OpenOpticsHeader(1, 0)
        pkt.AddHeader(hdr)
        uplinks[0].Send(pkt, uplinks[0].GetBroadcast(), 0x0800)

        # Run to mid-cycle 1 (slot 0 of cycle 1 is at 40-50 ms; we stop
        # at 45 ms). The packet would also fail to fit at cycle 1's
        # slot 0 (same 40 ms serialize > 10 ms deadline), so DrainSlice
        # at cycle 1's boundary again sees "late + idle" → leaves in
        # queue. Either way, no drop on the "late + idle" branch.
        ns.Simulator.Stop(ns.MicroSeconds(45_000))
        ns.Simulator.Run()

        self.assertEqual(app.GetSliceOverflowDrops(), 0,
                         "late-in-slice + idle link must defer (not "
                         "drop with overflow); preserves the rollover "
                         "behavior of the original fast-path")
        self.assertEqual(app.GetForwardedCount(), 0,
                         "no slot's active window can fit a 40 ms "
                         "packet at 1 Mbps")

    def test_two_uplinks_independent_runtime_budgets(self):
        """Runtime drain on uplink A doesn't deplete uplink B's slot
        capacity. Pre per-uplink m_linkFreeAt, m_bytesThisSlice was
        a single scalar summed across uplinks; uplink A filling its
        slot would falsely reject uplink B traffic in the same slot.

        Setup: nb_link=2, both at 20 Mbps (25_000 B / 10 ms slice). On
        uplink 0 inject 4 packets of 5008 B (20_032 B total — fits one
        link's per-slot budget). On uplink 1 inject 4 more 5008 B
        packets — combined load 40_064 B, exceeding a single uplink's
        budget but well within two uplinks' parallel capacity. With
        per-uplink linkFreeAt all 8 forward; with the old shared
        m_bytesThisSlice, the first ~4 (whichever uplink) would
        consume the budget and the rest would drop as overflow.
        """
        ns, app, host_peer, uplinks = self._make_tor(
            tor_id=0, nb_slices=4, slice_us=10_000, nb_uplinks=2,
        )
        app.SetUplinkLinkRateBps(20 * 1000 * 1000)  # 25_000 B / slice
        app.AddPerHopEntry(dst_node=1, arrival_ts=0, cur_node=0,
                           send_ts=0, send_port=0)
        app.AddPerHopEntry(dst_node=2, arrival_ts=0, cur_node=0,
                           send_ts=0, send_port=1)

        for dst in (1, 2):
            for _ in range(4):
                pkt = ns.Create["ns3::Packet"](5000)
                hdr = ns.openoptics.OpenOpticsHeader(dst, 0)
                pkt.AddHeader(hdr)
                uplinks[0].Send(pkt, uplinks[0].GetBroadcast(), 0x0800)

        ns.Simulator.Stop(ns.MilliSeconds(5))
        ns.Simulator.Run()

        self.assertEqual(app.GetForwardedCount(), 8,
                         "all 8 packets fit — each uplink's per-slot "
                         "budget is independent (per-uplink linkFreeAt)")
        self.assertEqual(app.GetSliceOverflowDrops(), 0,
                         "no overflow: combined load only exceeds a "
                         "single uplink's budget, not two uplinks'")


@skip_if_no_ns3
class TorGeneratedTableTests(unittest.TestCase):
    """ToR tests that drive the real utils.py per-hop table output."""

    def tearDown(self):
        if ns3_available():
            from ns import ns
            ns.Simulator.Destroy()

    def test_load_generated_per_hop_routing(self):
        """tor0's per_hop table after deploy_routing should have one entry per
        (dst, arrival_ts) reachable in a round-robin/direct setup."""
        from unittest.mock import patch
        from openoptics import OpticalTopo, OpticalRouting, Toolbox
        from openoptics.backends.ns3.backend import Ns3Backend

        nb_node = 4
        backend = Ns3Backend()
        with patch("openoptics.Toolbox.create_backend", return_value=backend):
            net = Toolbox.BaseNetwork(
                name="tor_gen_test", backend="ns3", nb_node=nb_node,
                time_slice_duration_us=10_000, guardband_ms=0,
                use_webserver=False,
            )
            net.deploy_topo(OpticalTopo.round_robin(nb_node=nb_node))
            paths = OpticalRouting.routing_direct(net.get_topo())
            net.deploy_routing(paths, routing_mode="Per-hop")

        # round_robin(4) has 3 time slices; tor0 has 3 destinations
        # (1, 2, 3) × 3 arrival slices = 9 per-hop entries.
        self.assertEqual(backend._tor_apps[0].GetPerHopEntryCount(), 9)
        # ip_to_dst has one entry per host (nb_node).
        self.assertEqual(
            backend._tor_apps[0].GetIpToDstEntryCount(), nb_node
        )
        # arrive_at_dst: one entry per ToR (its own tor_id).
        self.assertEqual(
            backend._tor_apps[0].GetArriveAtDstEntryCount(), 1
        )

        backend.stop()
        backend.cleanup()


if __name__ == "__main__":
    unittest.main()
