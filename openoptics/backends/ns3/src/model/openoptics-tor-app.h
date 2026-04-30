// Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
// Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
//
// Author: Yiming Lei (ylei@mpi-inf.mpg.de)
//
// License: Creative Commons NC BY SA 4.0
// https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en

#ifndef OPENOPTICS_TOR_APP_H
#define OPENOPTICS_TOR_APP_H

#include "openoptics-calendar-queue.h"
#include "openoptics-header.h"
#include "openoptics-source-route-header.h"

#include "ns3/application.h"
#include "ns3/callback.h"
#include "ns3/event-id.h"
#include "ns3/net-device.h"
#include "ns3/nstime.h"
#include "ns3/packet.h"
#include "ns3/ptr.h"
#include "ns3/random-variable-stream.h"
#include "ns3/traced-callback.h"

#include <cstdint>
#include <functional>
#include <string>
#include <unordered_map>
#include <vector>

namespace ns3
{
namespace openoptics
{

// Per-ToR application implementing the OpenOptics pipeline (host /
// uplink ingress, per-hop or source-routed forwarding, calendar-queue
// drain at each slice boundary).
//
// Tables mirror what openoptics/utils.py produces and what the Mininet
// BMv2 pipeline implements. ``arrive_at_dst`` is matched against
// ``OpenOpticsHeader.dst_node`` — the TableEntry field is named ``tor_id``
// for P4 compat but is semantically the destination node id.
class TorApp : public Application
{
  public:
    TorApp();
    ~TorApp() override;

    static TypeId GetTypeId();

    // Configuration — must be called before traffic starts.
    void SetTorId(uint32_t tor_id);
    void SetSliceDurationUs(uint64_t us);
    void SetNumSlices(uint32_t n);
    void SetCalendarQueueBufferCapacityBytes(uint64_t bytes);
    // Uplink data rate (bps), used by the per-slice byte-budget. With
    // rate ``r`` and slice duration ``d``, at most ``r * d / 8`` bytes
    // can leave a ToR per slice before bytes spill into the next slice.
    // Must be positive before StartApplication (enforced by NS_ABORT).
    void SetUplinkLinkRateBps(uint64_t bps);

    // OCS reconfiguration window at slice tail; the byte budget is
    // shrunk so the last byte leaves before the OCS goes dark. Default 0.
    void SetGuardbandUs(uint64_t us);

    // ToR-uplink-to-OCS propagation delay; added on top of the guardband
    // when shrinking the effective transmission window.
    void SetUplinkPropagationDelayUs(uint64_t us);

    // Opt-in P4-style ``verify_desired_node``. When on, SR hops whose
    // ``cur_node`` field disagrees with this ToR's id (and isn't the
    // wildcard 255) are dropped instead of resolved.
    void SetVerifySrCurNode(bool enable);

    // Wire up NetDevices (call after TorApp was added to a node). One
    // host device; one uplink device per OpenOptics link.
    void SetHostDevice(Ptr<NetDevice> device);
    uint32_t AddUplinkDevice(Ptr<NetDevice> device);

    // Table programming (called from Python load_table()).
    void AddIpToDst(const std::string& ip, uint32_t dst_node);
    void AddPerHopEntry(uint32_t dst_node,
                        uint32_t arrival_ts,
                        uint32_t cur_node,
                        uint32_t send_ts,
                        uint32_t send_port);
    void AddArriveAtDst(uint32_t dst_node, uint32_t host_port);

    // Source-routing table: one entry per (dst, arrival_ts) at the
    // ingress ToR; value is the full hop list (same shape as
    // utils.tor_table_routing_source).
    void AddSourceRoutingEntry(
        uint32_t dst_node,
        uint32_t arrival_ts,
        const std::vector<OpenOpticsSourceRouteHeader::Hop>& hops);
    void ClearSourceRouting();

    // cal_port_slice_to_node: resolves (dst, arrival_ts) -> (send_port,
    // send_ts) for SR hops with the "node-type" sentinel (send_ts == 255,
    // send_port_or_node is a node id).
    void AddCalPortSliceToNode(uint32_t dst_node,
                               uint32_t arrival_ts,
                               uint32_t send_port,
                               uint32_t send_ts);
    void ClearCalPortSliceToNode();

    void ClearIpToDst();
    void ClearPerHop();
    void ClearArriveAtDst();

    // Introspection.
    uint64_t GetIngressFromHostCount() const;
    uint64_t GetIngressFromUplinkCount() const;
    uint64_t GetForwardedCount() const;          // drained from calendar queue
    uint64_t GetDeliveredToHostCount() const;    // delivered via arrive_at_dst
    uint64_t GetDropCount() const;               // lookup miss + CQ overflow
    std::size_t GetPerHopEntryCount() const;
    std::size_t GetIpToDstEntryCount() const;
    std::size_t GetArriveAtDstEntryCount() const;
    std::size_t GetSourceRoutingEntryCount() const;
    std::size_t GetCalPortSliceToNodeEntryCount() const;
    std::size_t GetQueueDepth(uint32_t slice) const;
    uint64_t GetCalendarQueueDrops() const;
    // Per-slice byte-budget rejections — split out so capacity-overflow
    // drops are distinguishable from "real" drops (lookup miss, CQ full).
    uint64_t GetSliceOverflowDrops() const;
    // Per-drop-site break-down (sums to GetDropCount()). Surfaced by
    // print_report to attribute drops to a specific failure mode.
    uint64_t GetDropFromHostNoIp() const;
    uint64_t GetDropFromUplinkParse() const;
    uint64_t GetDropFromUplinkProtocol() const;
    uint64_t GetDropForwardSendFail() const;
    uint64_t GetDropPerHopMissed() const;
    uint64_t GetDropPerHopSentinel() const;
    uint64_t GetDropForwardPort() const;
    uint64_t GetDropForwardCq() const;
    uint64_t GetDropResolveRandom() const;
    uint64_t GetDropResolveNode() const;
    uint64_t GetDropResolveFallthrough() const;
    uint64_t GetDropSrEmpty() const;
    uint64_t GetDropSrIngressBadCur() const;
    uint64_t GetDropSrUplinkSize() const;
    uint64_t GetDropSrEndNotDst() const;
    uint64_t GetDropSrTransitBadCur() const;
    uint64_t GetDropAdmFail() const;

    // Per-hop admission control. When on, HandleRoutedPacket walks
    // ``(dst, arrival_ts + offset)`` and forwards on the first entry
    // whose AdmCheck passes; otherwise the packet drops to
    // ``m_dropAdmFail``. Off by default.
    void SetAdmissionControl(bool enabled);
    bool GetAdmissionControl() const;

    // Aggregate queue metrics for dashboard snapshots.
    uint64_t GetTotalQueueDepth() const;   // sum over all slices
    uint64_t GetPeakQueueDepth() const;    // max over all slices
    uint64_t GetTotalQueueBytes() const;   // queued bytes across all slices/uplinks
    uint64_t GetPeakQueueBytes() const;    // max total queued bytes observed

    // Schedule periodic snapshot emission every ``interval``; cancelled
    // on StopApplication.
    void ScheduleSnapshots(Time interval);

    // std::function listener for the Python dashboard sink (cppyy can't
    // bind Python callables via MakeCallback). Fires alongside
    // m_snapshotTrace.
    using SnapshotListener =
        std::function<void(uint64_t /*sim_time_us*/,
                           uint32_t /*tor_id*/,
                           uint64_t /*forwarded*/,
                           uint64_t /*delivered*/,
                           uint64_t /*drops*/,
                           uint64_t /*total_queue_depth*/,
                           uint64_t /*peak_queue_depth*/,
                           uint64_t /*total_queue_bytes*/,
                           uint64_t /*peak_queue_bytes*/,
                           uint64_t /*cq_drops*/,
                           uint64_t /*ingress_from_host*/,
                           uint64_t /*ingress_from_uplink*/,
                           uint64_t /*overflow_drops*/)>;
    void SetSnapshotListener(SnapshotListener fn);

  protected:
    void StartApplication() override;
    void StopApplication() override;

  private:
    // Incoming-packet handlers, wired via Node::RegisterProtocolHandler.
    void ReceiveFromHost(Ptr<NetDevice> device,
                         Ptr<const Packet> packet,
                         uint16_t protocol,
                         const Address& src,
                         const Address& dst,
                         NetDevice::PacketType packetType);
    void ReceiveFromUplink(Ptr<NetDevice> device,
                           Ptr<const Packet> packet,
                           uint16_t protocol,
                           const Address& src,
                           const Address& dst,
                           NetDevice::PacketType packetType);

    // Drain the current slice and re-schedule for the next boundary.
    void OnSliceBoundary();
    void ScheduleNextSliceBoundary();

    // Pop and transmit every packet in m_cq[slice] on its stored uplink.
    // Shared by OnSliceBoundary and the same-slice immediate-send path
    // in HandleRoutedPacket.
    void DrainSlice(uint32_t slice);

    // Plan-time admission for ADM mode: would a packet of ``pkt_bytes``
    // enqueued for ``(target_slice, uplink_idx)`` drain inside that
    // slot's active window, given bytes already queued there for that
    // uplink? Same-slice case has only the slot remainder available;
    // future slots get the full active window. Side-effect-free.
    bool AdmCheck(uint32_t target_slice, uint32_t uplink_idx,
                  std::size_t pkt_bytes) const;

    // Runtime admission for the drain / same-slice path. True iff
    //
    //   max(now, m_linkFreeAt[i]) + serialize(pkt_bytes) <= deadline
    //
    // where ``deadline = slot_start + m_effectiveActiveUs``. Side-effect
    // free. Distinct from AdmCheck, which asks about queue depth at
    // enqueue time rather than link-in-flight state at drain time.
    bool CanFinishInActiveWindow(uint32_t uplink_idx, uint32_t slot,
                                 std::size_t pkt_bytes) const;

    // Recompute m_effectiveActiveUs after slice duration / guardband /
    // propagation-delay setters change.
    void RecomputeEffectiveActiveUs();

    // Resize m_cqBytesPerSlot to (m_numSlices, m_uplinks.size()),
    // preserving existing entries. Tolerates SetNumSlices and
    // AddUplinkDevice in any order.
    void ResizeCqBytesPerSlot();

    // Rebuild m_cq with one calendar queue per uplink, each sized to
    // m_numSlices. No-op once StartApplication has run (would discard live
    // queue state). Tolerates configuration setters in any order.
    void EnsureCalendarQueues();

    void RemoveBufferedPacketBytes(uint32_t slice,
                                   uint32_t uplink,
                                   std::size_t pkt_bytes);

    // Periodic snapshot event: fires m_snapshotTrace and self-reschedules.
    void EmitSnapshot();

    uint32_t CurrentSlice() const;
    uint64_t TimeUntilSliceStartUs(uint32_t slice) const;

    // Extract destination IP (as dotted-quad string) from a packet whose
    // head is an IPv4 header (dst is offset 16).
    static std::string ExtractIpv4Dst(Ptr<const Packet> packet);

    // Per-hop forwarding path: look up per_hop_routing(dst, arrival_ts)
    // (with the offset walk if admission control is on) and dispatch via
    // ForwardOnSlice. Called from both host and uplink ingress after the
    // OpenOpticsHeader is resolved.
    void HandleRoutedPacket(Ptr<Packet> packet_with_header,
                            uint32_t dst_node,
                            uint32_t arrival_ts,
                            uint16_t protocol);

    // Source-routing host ingress: stamps the SR header (+
    // OpenOpticsHeader) and forwards the first hop. Returns false if no
    // SR entry was found, signalling the caller to fall through to
    // per-hop.
    bool TrySourceRoutingIngress(Ptr<const Packet> raw_ip_packet,
                                 uint32_t dst_node,
                                 uint32_t arrival_ts,
                                 uint16_t host_protocol);

    // Source-routing uplink handler. The caller has already peeled
    // OpenOpticsHeader to read its mode byte. Pops the SR header,
    // advances the hop pointer, then either forwards to the next hop or
    // delivers locally.
    void HandleSourceRoutedUplink(Ptr<Packet> pkt_without_oo_header,
                                  const OpenOpticsHeader& oo,
                                  uint16_t carried_protocol);

    // Resolve a (possibly-sentineled) hop into (send_port, send_ts).
    // Three patterns:
    //   - plain port-type:                  direct mapping
    //   - node-type (send_ts == 255):       look up m_calPortSliceToNode
    //   - random-port VLB (port_or_node == 255): random uplink, current slice
    // On failure, increments m_drops and returns false.
    bool ResolveHop(const OpenOpticsSourceRouteHeader::Hop& hop,
                    uint32_t arrival_ts,
                    uint32_t* out_send_port,
                    uint32_t* out_send_ts);

    // Send-on-slice helper shared by per-hop and source-routing: enqueue
    // for a future slice, or drain immediately if it's the current slice.
    void ForwardOnSlice(Ptr<Packet> pkt_with_headers,
                        uint32_t send_port,
                        uint32_t send_ts,
                        uint16_t protocol);


    // Tables.
    std::unordered_map<std::string, uint32_t> m_ipToDst;
    std::unordered_map<uint64_t, uint32_t> m_perHopSendPort;  // (dst,ats) -> port
    std::unordered_map<uint64_t, uint32_t> m_perHopSendTs;    // (dst,ats) -> ts
    std::unordered_map<uint32_t, uint32_t> m_arriveAtDst;     // dst_node -> host_port
    std::unordered_map<uint64_t,
                       std::vector<OpenOpticsSourceRouteHeader::Hop>>
        m_sourceRouting;                                      // (dst,ats) -> hops
    std::unordered_map<uint64_t, uint32_t> m_calSendPort;     // (dst,ats) -> port
    std::unordered_map<uint64_t, uint32_t> m_calSendTs;       // (dst,ats) -> ts

    // RNG for the VLB random-port sentinel. Lazy: tests that never
    // exercise random hops don't pay for the UniformRandomVariable setup.
    Ptr<UniformRandomVariable> m_rng;

    // Topology.
    Ptr<NetDevice> m_hostDev;
    std::vector<Ptr<NetDevice>> m_uplinks;

    // Clock config.
    uint32_t m_torId;
    uint64_t m_sliceDurationUs;
    uint32_t m_numSlices;
    uint64_t m_cqBufferCapacityBytes;

    // One calendar queue per uplink, each sliced by slot. Sized lazily
    // by AddUplinkDevice / SetNumSlices via
    // EnsureCalendarQueues(); the order they're called doesn't matter.
    std::vector<CalendarQueue<Ptr<Packet>>> m_cq;

    // Pending slice-boundary event.
    EventId m_sliceBoundaryEvent;

    // Counters.
    uint64_t m_ingressFromHost;
    uint64_t m_ingressFromUplink;
    uint64_t m_forwarded;
    uint64_t m_deliveredToHost;
    uint64_t m_drops;
    uint64_t m_sliceOverflowDrops;
    // Per-drop-site break-down (sums to m_drops). Each counter is
    // incremented at exactly one ++m_drops site so the after-run report
    // attributes drops without extra instrumentation.
    uint64_t m_dropFromHostNoIp = 0;
    uint64_t m_dropFromUplinkParse = 0;
    uint64_t m_dropFromUplinkProtocol = 0;
    uint64_t m_dropForwardSendFail = 0;
    uint64_t m_dropPerHopMissed = 0;
    uint64_t m_dropPerHopSentinel = 0;
    uint64_t m_dropForwardPort = 0;
    uint64_t m_dropForwardCq = 0;
    uint64_t m_dropResolveRandom = 0;
    uint64_t m_dropResolveNode = 0;
    uint64_t m_dropResolveFallthrough = 0;
    uint64_t m_dropSrEmpty = 0;
    uint64_t m_dropSrIngressBadCur = 0;
    uint64_t m_dropSrUplinkSize = 0;
    uint64_t m_dropSrEndNotDst = 0;
    uint64_t m_dropSrTransitBadCur = 0;
    uint64_t m_dropAdmFail = 0;            // ADM-mode: no slot passed AdmCheck
    uint64_t m_cqBufferedBytes;
    uint64_t m_cqPeakBufferedBytes;

    // ADM mode: see SetAdmissionControl().
    bool m_admissionControl = false;
    // Bytes queued in the calendar queue, per (slot, uplink). Updated
    // alongside Enqueue/Dequeue so AdmCheck is O(1) and per-uplink
    // contention is independent. Sized lazily by SetNumSlices and
    // AddUplinkDevice in any order.
    std::vector<std::vector<uint64_t>> m_cqBytesPerSlot;

    // Uplink rate (bps). Must be positive by StartApplication (NS_ABORT).
    // No scalar bytes-this-slice counter is needed because absolute
    // simulator timestamps can't carry stale state across cycle wrap.
    uint64_t m_uplinkLinkRateBps;

    // Per-uplink "next free" timestamp — when uplink i will be free to
    // start serializing the next byte. Bumped after every dev->Send by
    // the packet's serialization time. Read by CanFinishInActiveWindow.
    // Sized in lockstep with m_uplinks.
    std::vector<Time> m_linkFreeAt;

    // Active-window inputs: guardband + uplink propagation delay shrink
    // the in-slice window m_effectiveActiveUs (cached; recomputed by
    // RecomputeEffectiveActiveUs).
    uint64_t m_guardbandUs;
    uint64_t m_ocsLinkDelayUs;
    uint64_t m_effectiveActiveUs;

    // Opt-in P4-style verify_desired_node gate for SR hops.
    bool m_verifySrCurNode;

    // Periodic snapshot state.
    Time m_snapshotInterval;
    EventId m_snapshotEvent;
    // Payload: (sim_time_us, tor_id, forwarded, delivered, drops,
    //           total_queue_depth, peak_queue_depth, total_queue_bytes,
    //           peak_queue_bytes, cq_drops, ingress_from_host,
    //           ingress_from_uplink, overflow_drops).
    TracedCallback<uint64_t, uint32_t, uint64_t, uint64_t, uint64_t,
                   uint64_t, uint64_t, uint64_t, uint64_t, uint64_t,
                   uint64_t, uint64_t, uint64_t>
        m_snapshotTrace;
    SnapshotListener m_snapshotListener;

    // Compose the LUT key for per-hop / SR / cal_port_slice_to_node tables.
    static uint64_t PerHopKey(uint32_t dst_node, uint32_t arrival_ts);
};

} // namespace openoptics
} // namespace ns3

#endif // OPENOPTICS_TOR_APP_H
