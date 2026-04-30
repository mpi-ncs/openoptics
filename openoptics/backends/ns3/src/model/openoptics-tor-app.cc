// Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
// Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
//
// Author: Yiming Lei (ylei@mpi-inf.mpg.de)
//
// License: Creative Commons NC BY SA 4.0
// https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en

#include "openoptics-tor-app.h"

#include "openoptics-header.h"

#include "ns3/log.h"
#include "ns3/node.h"
#include "ns3/nstime.h"
#include "ns3/simulator.h"

#include <algorithm>
#include <sstream>

namespace ns3
{
namespace openoptics
{

NS_LOG_COMPONENT_DEFINE("OpenOpticsTor");
NS_OBJECT_ENSURE_REGISTERED(TorApp);

TypeId
TorApp::GetTypeId()
{
    static TypeId tid =
        TypeId("ns3::openoptics::TorApp")
            .SetParent<Application>()
            .SetGroupName("OpenOptics")
            .AddConstructor<TorApp>()
            .AddTraceSource("Snapshot",
                            "Periodic aggregate counters: (sim_time_us, "
                            "tor_id, forwarded, delivered_to_host, drops, "
                            "total_queue_depth, peak_queue_depth, "
                            "total_queue_bytes, peak_queue_bytes, cq_drops, "
                            "ingress_from_host, ingress_from_uplink, "
                            "overflow_drops).",
                            MakeTraceSourceAccessor(&TorApp::m_snapshotTrace),
                            "ns3::openoptics::TorApp::SnapshotCallback");
    return tid;
}

TorApp::TorApp()
    : m_torId(0),
      m_sliceDurationUs(0),
      m_numSlices(0),
      m_cqBufferCapacityBytes(1048576),
      // m_cq is empty until AddUplinkDevice / SetNumSlices populate it
      // via EnsureCalendarQueues. StartApplication asserts non-empty.
      m_ingressFromHost(0),
      m_ingressFromUplink(0),
      m_forwarded(0),
      m_deliveredToHost(0),
      m_drops(0),
      m_sliceOverflowDrops(0),
      m_cqBufferedBytes(0),
      m_cqPeakBufferedBytes(0),
      m_uplinkLinkRateBps(0),
      m_guardbandUs(0),
      m_ocsLinkDelayUs(0),
      m_effectiveActiveUs(0),
      m_verifySrCurNode(false),
      m_snapshotInterval(Seconds(0))
{
}

TorApp::~TorApp() = default;

// --- Config setters ---------------------------------------------------------

void
TorApp::SetTorId(uint32_t tor_id)
{
    m_torId = tor_id;
}

void
TorApp::SetSliceDurationUs(uint64_t us)
{
    m_sliceDurationUs = us;
    RecomputeEffectiveActiveUs();
}

void
TorApp::SetNumSlices(uint32_t n)
{
    m_numSlices = n;
    // Resize CQs only if we haven't started yet; once running, resize
    // would discard live state (configure before StartApplication).
    EnsureCalendarQueues();
    ResizeCqBytesPerSlot();
}

void
TorApp::SetCalendarQueueBufferCapacityBytes(uint64_t bytes)
{
    NS_ABORT_MSG_IF(bytes == 0,
                    "TorApp: calendar queue byte buffer capacity must be positive");
    m_cqBufferCapacityBytes = bytes;
}

void
TorApp::SetUplinkLinkRateBps(uint64_t bps)
{
    m_uplinkLinkRateBps = bps;
}

void
TorApp::SetGuardbandUs(uint64_t us)
{
    m_guardbandUs = us;
    RecomputeEffectiveActiveUs();
}

void
TorApp::SetUplinkPropagationDelayUs(uint64_t us)
{
    m_ocsLinkDelayUs = us;
    RecomputeEffectiveActiveUs();
}

void
TorApp::SetVerifySrCurNode(bool enable)
{
    m_verifySrCurNode = enable;
}

namespace {
// Shared helper so the two SR dispatch sites stay in lockstep.
inline bool
HopBelongsHere(uint32_t cur_node, uint32_t tor_id)
{
    return cur_node == 255u || cur_node == tor_id;
}
} // namespace

void
TorApp::RecomputeEffectiveActiveUs()
{
    const uint64_t overhead = m_guardbandUs + m_ocsLinkDelayUs;
    m_effectiveActiveUs =
        (overhead >= m_sliceDurationUs) ? 0 : (m_sliceDurationUs - overhead);
}

void
TorApp::ResizeCqBytesPerSlot()
{
    const std::size_t slots = m_numSlices > 0 ? m_numSlices : 1;
    const std::size_t uplinks = m_uplinks.size();
    m_cqBytesPerSlot.assign(slots, std::vector<uint64_t>(uplinks, 0));
}

void
TorApp::EnsureCalendarQueues()
{
    if (m_sliceBoundaryEvent.IsPending())
    {
        return;   // running — don't discard live queue state
    }
    const std::size_t slots = m_numSlices > 0 ? m_numSlices : 1;
    m_cq.clear();
    m_cq.reserve(m_uplinks.size());
    for (std::size_t i = 0; i < m_uplinks.size(); ++i)
    {
        m_cq.emplace_back(slots);
    }
}

void
TorApp::RemoveBufferedPacketBytes(uint32_t slice,
                                  uint32_t uplink,
                                  std::size_t pkt_bytes)
{
    const uint64_t bytes = static_cast<uint64_t>(pkt_bytes);
    m_cqBufferedBytes = (m_cqBufferedBytes >= bytes)
                            ? m_cqBufferedBytes - bytes
                            : 0;
    if (slice < m_cqBytesPerSlot.size() &&
        uplink < m_cqBytesPerSlot[slice].size())
    {
        uint64_t& cell = m_cqBytesPerSlot[slice][uplink];
        cell = (cell >= bytes) ? cell - bytes : 0;
    }
}

// --- Topology wiring --------------------------------------------------------

void
TorApp::SetHostDevice(Ptr<NetDevice> device)
{
    NS_ASSERT_MSG(GetNode() != nullptr,
                  "SetHostDevice called before app was added to a node");
    m_hostDev = device;
    GetNode()->RegisterProtocolHandler(
        MakeCallback(&TorApp::ReceiveFromHost, this),
        /*protocol=*/0,
        device,
        /*promiscuous=*/true);
}

uint32_t
TorApp::AddUplinkDevice(Ptr<NetDevice> device)
{
    NS_ASSERT_MSG(GetNode() != nullptr,
                  "AddUplinkDevice called before app was added to a node");
    uint32_t idx = m_uplinks.size();
    m_uplinks.push_back(device);
    m_linkFreeAt.push_back(Time(0));
    GetNode()->RegisterProtocolHandler(
        MakeCallback(&TorApp::ReceiveFromUplink, this),
        /*protocol=*/0,
        device,
        /*promiscuous=*/true);
    EnsureCalendarQueues();
    ResizeCqBytesPerSlot();
    return idx;
}

// --- Table programming ------------------------------------------------------

void
TorApp::AddIpToDst(const std::string& ip, uint32_t dst_node)
{
    m_ipToDst[ip] = dst_node;
}

uint64_t
TorApp::PerHopKey(uint32_t dst_node, uint32_t arrival_ts)
{
    return (static_cast<uint64_t>(dst_node) << 32) | arrival_ts;
}

void
TorApp::AddPerHopEntry(uint32_t dst_node,
                       uint32_t arrival_ts,
                       uint32_t /*cur_node*/,
                       uint32_t send_ts,
                       uint32_t send_port)
{
    // cur_node is always this ToR (Python shards entries per-ToR), so we
    // ignore it here.
    uint64_t k = PerHopKey(dst_node, arrival_ts);
    m_perHopSendPort[k] = send_port;
    m_perHopSendTs[k] = send_ts;
}

void
TorApp::AddArriveAtDst(uint32_t dst_node, uint32_t host_port)
{
    m_arriveAtDst[dst_node] = host_port;
}

void
TorApp::AddSourceRoutingEntry(
    uint32_t dst_node,
    uint32_t arrival_ts,
    const std::vector<OpenOpticsSourceRouteHeader::Hop>& hops)
{
    m_sourceRouting[PerHopKey(dst_node, arrival_ts)] = hops;
}

void
TorApp::ClearSourceRouting()
{
    m_sourceRouting.clear();
}

void
TorApp::AddCalPortSliceToNode(uint32_t dst_node,
                              uint32_t arrival_ts,
                              uint32_t send_port,
                              uint32_t send_ts)
{
    const uint64_t k = PerHopKey(dst_node, arrival_ts);
    m_calSendPort[k] = send_port;
    m_calSendTs[k] = send_ts;
}

void
TorApp::ClearCalPortSliceToNode()
{
    m_calSendPort.clear();
    m_calSendTs.clear();
}

void
TorApp::ClearIpToDst()
{
    m_ipToDst.clear();
}

void
TorApp::ClearPerHop()
{
    m_perHopSendPort.clear();
    m_perHopSendTs.clear();
}

void
TorApp::ClearArriveAtDst()
{
    m_arriveAtDst.clear();
}

// --- Introspection ----------------------------------------------------------

uint64_t TorApp::GetIngressFromHostCount() const   { return m_ingressFromHost; }
uint64_t TorApp::GetIngressFromUplinkCount() const { return m_ingressFromUplink; }
uint64_t TorApp::GetForwardedCount() const         { return m_forwarded; }
uint64_t TorApp::GetDeliveredToHostCount() const   { return m_deliveredToHost; }
uint64_t TorApp::GetDropCount() const              { return m_drops; }
std::size_t TorApp::GetPerHopEntryCount() const    { return m_perHopSendPort.size(); }
std::size_t TorApp::GetIpToDstEntryCount() const   { return m_ipToDst.size(); }
std::size_t TorApp::GetArriveAtDstEntryCount() const { return m_arriveAtDst.size(); }
std::size_t TorApp::GetSourceRoutingEntryCount() const { return m_sourceRouting.size(); }
std::size_t TorApp::GetCalPortSliceToNodeEntryCount() const { return m_calSendPort.size(); }
std::size_t TorApp::GetQueueDepth(uint32_t slice) const
{
    std::size_t total = 0;
    for (const auto& cq : m_cq) total += cq.Depth(slice);
    return total;
}
uint64_t TorApp::GetCalendarQueueDrops() const
{
    return m_dropForwardCq;
}
uint64_t TorApp::GetSliceOverflowDrops() const { return m_sliceOverflowDrops; }
uint64_t TorApp::GetDropFromHostNoIp() const         { return m_dropFromHostNoIp; }
uint64_t TorApp::GetDropFromUplinkParse() const      { return m_dropFromUplinkParse; }
uint64_t TorApp::GetDropFromUplinkProtocol() const   { return m_dropFromUplinkProtocol; }
uint64_t TorApp::GetDropForwardSendFail() const      { return m_dropForwardSendFail; }
uint64_t TorApp::GetDropPerHopMissed() const         { return m_dropPerHopMissed; }
uint64_t TorApp::GetDropPerHopSentinel() const       { return m_dropPerHopSentinel; }
uint64_t TorApp::GetDropForwardPort() const          { return m_dropForwardPort; }
uint64_t TorApp::GetDropForwardCq() const            { return m_dropForwardCq; }
uint64_t TorApp::GetDropResolveRandom() const        { return m_dropResolveRandom; }
uint64_t TorApp::GetDropResolveNode() const          { return m_dropResolveNode; }
uint64_t TorApp::GetDropResolveFallthrough() const   { return m_dropResolveFallthrough; }
uint64_t TorApp::GetDropSrEmpty() const              { return m_dropSrEmpty; }
uint64_t TorApp::GetDropSrIngressBadCur() const      { return m_dropSrIngressBadCur; }
uint64_t TorApp::GetDropSrUplinkSize() const         { return m_dropSrUplinkSize; }
uint64_t TorApp::GetDropSrEndNotDst() const          { return m_dropSrEndNotDst; }
uint64_t TorApp::GetDropSrTransitBadCur() const      { return m_dropSrTransitBadCur; }
uint64_t TorApp::GetDropAdmFail() const              { return m_dropAdmFail; }

void TorApp::SetAdmissionControl(bool enabled)        { m_admissionControl = enabled; }
bool TorApp::GetAdmissionControl() const              { return m_admissionControl; }

uint64_t
TorApp::GetTotalQueueDepth() const
{
    uint64_t total = 0;
    for (const auto& cq : m_cq)
    {
        for (std::size_t s = 0; s < cq.NumSlices(); ++s)
        {
            total += cq.Depth(s);
        }
    }
    return total;
}

uint64_t
TorApp::GetPeakQueueDepth() const
{
    // Max depth across any single (slot, uplink) bucket.
    uint64_t peak = 0;
    for (const auto& cq : m_cq)
    {
        for (std::size_t s = 0; s < cq.NumSlices(); ++s)
        {
            const uint64_t d = cq.Depth(s);
            if (d > peak)
            {
                peak = d;
            }
        }
    }
    return peak;
}

uint64_t
TorApp::GetTotalQueueBytes() const
{
    return m_cqBufferedBytes;
}

uint64_t
TorApp::GetPeakQueueBytes() const
{
    return m_cqPeakBufferedBytes;
}

// --- Slice clock ------------------------------------------------------------

uint32_t
TorApp::CurrentSlice() const
{
    if (m_sliceDurationUs == 0 || m_numSlices == 0)
    {
        return 0;
    }
    uint64_t now = Simulator::Now().GetMicroSeconds();
    return static_cast<uint32_t>((now / m_sliceDurationUs) % m_numSlices);
}

uint64_t
TorApp::TimeUntilSliceStartUs(uint32_t slice) const
{
    if (m_sliceDurationUs == 0 || m_numSlices == 0)
    {
        return 0;
    }
    uint64_t now = Simulator::Now().GetMicroSeconds();
    uint64_t cur_slice = (now / m_sliceDurationUs) % m_numSlices;
    uint64_t cur_slice_start = now - (now % m_sliceDurationUs);
    uint32_t delta = (slice + m_numSlices - cur_slice) % m_numSlices;
    return (cur_slice_start + static_cast<uint64_t>(delta) * m_sliceDurationUs) - now
           + (delta == 0 ? 0 : 0);
}

void
TorApp::ScheduleNextSliceBoundary()
{
    if (m_sliceDurationUs == 0)
    {
        return;
    }
    uint64_t now = Simulator::Now().GetMicroSeconds();
    uint64_t next = ((now / m_sliceDurationUs) + 1) * m_sliceDurationUs;
    Time delay = MicroSeconds(next - now);
    m_sliceBoundaryEvent =
        Simulator::Schedule(delay, &TorApp::OnSliceBoundary, this);
}

void
TorApp::OnSliceBoundary()
{
    // m_linkFreeAt is an absolute simulator timestamp, so cycle wrap
    // can't leave stale state — no reset needed.
    DrainSlice(CurrentSlice());
    ScheduleNextSliceBoundary();
}

void
TorApp::DrainSlice(uint32_t slice)
{
    // Drain each uplink's slot independently. Peek-then-Dequeue is
    // load-bearing: a head packet that can't be admitted right now may
    // need to stay in the queue for the next cycle (late-rollover case
    // below). Re-enqueue would break FIFO.
    for (uint32_t uplink = 0; uplink < m_cq.size(); ++uplink)
    {
        Ptr<Packet> pkt;
        uint32_t cookie;
        while (m_cq[uplink].Peek(slice, &pkt, &cookie))
        {
            const std::size_t pkt_bytes = pkt->GetSize();
            if (!CanFinishInActiveWindow(uplink, slice, pkt_bytes))
            {
                if (m_linkFreeAt[uplink] > Simulator::Now())
                {
                    // Byte-budget overflow: the uplink is still busy
                    // serializing earlier sends. Drop — spilling past
                    // the boundary would misroute under the next OCS
                    // schedule.
                    m_cq[uplink].Dequeue(slice, &pkt, &cookie);
                    RemoveBufferedPacketBytes(slice, uplink, pkt_bytes);
                    ++m_drops;
                    ++m_sliceOverflowDrops;
                    continue;
                }
                // Late-in-slice + link idle: too close to the active-
                // window deadline to finish this packet. Leave it for
                // the next cycle's drain. Later packets in this bucket
                // would be even later, so stop draining this uplink.
                break;
            }
            // Take path: dequeue, update bookkeeping, then advance
            // m_linkFreeAt *before* dev->Send so re-entrant code sees
            // the updated state.
            m_cq[uplink].Dequeue(slice, &pkt, &cookie);
            RemoveBufferedPacketBytes(slice, uplink, pkt_bytes);
            const uint64_t serialize_ns =
                (static_cast<uint64_t>(pkt_bytes) * 8ULL * 1000000000ULL
                 + m_uplinkLinkRateBps - 1ULL)
                / m_uplinkLinkRateBps;
            const Time now = Simulator::Now();
            m_linkFreeAt[uplink] =
                std::max(now, m_linkFreeAt[uplink])
                + NanoSeconds(serialize_ns);
            Ptr<NetDevice> dev = m_uplinks[uplink];
            if (!dev->Send(pkt, dev->GetBroadcast(), /*protocol=*/0x0800))
            {
                ++m_drops;
                ++m_dropForwardSendFail;
                continue;
            }
            ++m_forwarded;
        }
    }
}

bool
TorApp::AdmCheck(uint32_t target_slice, uint32_t uplink_idx,
                 std::size_t pkt_bytes) const
{
    // Time available in target_slice's active window. Same-slice has
    // only the remainder left; future slices give the full window.
    uint64_t available_ns;
    const uint64_t effective_active_ns =
        static_cast<uint64_t>(m_effectiveActiveUs) * 1000ULL;
    if (target_slice == CurrentSlice())
    {
        const uint64_t now_ns = Simulator::Now().GetNanoSeconds();
        const uint64_t slot_dur_ns =
            static_cast<uint64_t>(m_sliceDurationUs) * 1000ULL;
        const uint64_t admit_offset_ns = now_ns % slot_dur_ns;
        if (admit_offset_ns >= effective_active_ns)
        {
            return false;   // already past the active window
        }
        available_ns = effective_active_ns - admit_offset_ns;
    }
    else
    {
        available_ns = effective_active_ns;
    }
    // Bytes already queued at (slot, uplink) eat into drain time;
    // other uplinks don't compete for this one's capacity.
    uint64_t queued_bytes = 0;
    if (target_slice < m_cqBytesPerSlot.size() &&
        uplink_idx < m_cqBytesPerSlot[target_slice].size())
    {
        queued_bytes = m_cqBytesPerSlot[target_slice][uplink_idx];
    }
    // budget = rate * available_ns / 1e9 / 8. Order to avoid overflow.
    const uint64_t budget_bytes =
        (m_uplinkLinkRateBps / 8) * available_ns / 1000000000ULL;
    return queued_bytes + pkt_bytes <= budget_bytes;
}

bool
TorApp::CanFinishInActiveWindow(uint32_t uplink_idx, uint32_t slot,
                                std::size_t pkt_bytes) const
{
    if (uplink_idx >= m_linkFreeAt.size() || m_uplinkLinkRateBps == 0
        || m_sliceDurationUs == 0 || m_numSlices == 0)
    {
        return false;
    }
    const Time now = Simulator::Now();
    const Time link_free = std::max(now, m_linkFreeAt[uplink_idx]);

    // Slot start: the current slot's start (already in the past) if
    // ``slot == cur_slice``, else the next future occurrence of that
    // slot id within the cycle.
    const uint64_t now_us = now.GetMicroSeconds();
    const uint64_t cur_slot_start_us = now_us - (now_us % m_sliceDurationUs);
    const uint32_t cur_slice =
        static_cast<uint32_t>((now_us / m_sliceDurationUs) % m_numSlices);
    Time slot_start;
    if (slot == cur_slice)
    {
        slot_start = MicroSeconds(cur_slot_start_us);
    }
    else
    {
        const uint32_t delta = (slot + m_numSlices - cur_slice) % m_numSlices;
        slot_start = MicroSeconds(cur_slot_start_us
                                  + static_cast<uint64_t>(delta)
                                        * m_sliceDurationUs);
    }
    const Time deadline =
        slot_start + MicroSeconds(m_effectiveActiveUs);

    // Serialize in ns to avoid µs-rounding for small packets at high
    // rates. Round up so we're pessimistic (reject borderline-late
    // packets rather than overrunning the window).
    const uint64_t serialize_ns =
        (static_cast<uint64_t>(pkt_bytes) * 8ULL * 1000000000ULL
         + m_uplinkLinkRateBps - 1ULL)
        / m_uplinkLinkRateBps;
    return (link_free + NanoSeconds(serialize_ns)) <= deadline;
}


// --- Application lifecycle --------------------------------------------------

void
TorApp::StartApplication()
{
    // Fail loudly when required config is missing, rather than silently
    // no-op'ing in the data plane. Production wires this via the Python
    // backend; tests must do the same in their fixture.
    NS_ABORT_MSG_IF(m_uplinkLinkRateBps == 0,
                    "TorApp: SetUplinkLinkRateBps was never called");
    NS_ABORT_MSG_IF(m_sliceDurationUs == 0,
                    "TorApp: SetSliceDurationUs was never called");
    NS_ABORT_MSG_IF(m_uplinks.empty(),
                    "TorApp: AddUplinkDevice was never called");
    NS_ABORT_MSG_IF(m_cq.size() != m_uplinks.size(),
                    "TorApp: m_cq is out of sync with m_uplinks "
                    "(EnsureCalendarQueues invariant violated)");
    ScheduleNextSliceBoundary();
}

void
TorApp::StopApplication()
{
    if (m_sliceBoundaryEvent.IsPending())
    {
        Simulator::Cancel(m_sliceBoundaryEvent);
    }
    if (m_snapshotEvent.IsPending())
    {
        Simulator::Cancel(m_snapshotEvent);
    }
}

void
TorApp::ScheduleSnapshots(Time interval)
{
    m_snapshotInterval = interval;
    // Fire once immediately (t=now snapshot), then self-reschedule.
    EmitSnapshot();
}

void
TorApp::SetSnapshotListener(TorApp::SnapshotListener fn)
{
    m_snapshotListener = std::move(fn);
}

void
TorApp::EmitSnapshot()
{
    const uint64_t t = static_cast<uint64_t>(Simulator::Now().GetMicroSeconds());
    const uint64_t total = GetTotalQueueDepth();
    const uint64_t peak = GetPeakQueueDepth();
    const uint64_t total_bytes = GetTotalQueueBytes();
    const uint64_t peak_bytes = GetPeakQueueBytes();
    const uint64_t cqd = GetCalendarQueueDrops();
    m_snapshotTrace(t, m_torId, m_forwarded, m_deliveredToHost, m_drops,
                    total, peak, total_bytes, peak_bytes, cqd,
                    m_ingressFromHost, m_ingressFromUplink,
                    m_sliceOverflowDrops);
    if (m_snapshotListener)
    {
        m_snapshotListener(t, m_torId, m_forwarded, m_deliveredToHost, m_drops,
                           total, peak, total_bytes, peak_bytes, cqd,
                           m_ingressFromHost, m_ingressFromUplink,
                           m_sliceOverflowDrops);
    }
    m_snapshotEvent =
        Simulator::Schedule(m_snapshotInterval, &TorApp::EmitSnapshot, this);
}

// --- Packet parsing helpers -------------------------------------------------

std::string
TorApp::ExtractIpv4Dst(Ptr<const Packet> packet)
{
    // RegisterProtocolHandler strips L2 framing, so the head is the
    // IPv4 header — dst IP lives at byte 16.
    uint8_t buf[20] = {0};
    uint32_t n = packet->CopyData(buf, 20);
    if (n < 20)
    {
        return std::string();
    }
    std::ostringstream os;
    os << static_cast<int>(buf[16]) << '.' << static_cast<int>(buf[17]) << '.'
       << static_cast<int>(buf[18]) << '.' << static_cast<int>(buf[19]);
    return os.str();
}


// --- Ingress handlers -------------------------------------------------------

void
TorApp::ReceiveFromHost(Ptr<NetDevice> /*device*/,
                        Ptr<const Packet> packet,
                        uint16_t protocol,
                        const Address& /*src*/,
                        const Address& /*dst*/,
                        NetDevice::PacketType /*packetType*/)
{
    ++m_ingressFromHost;

    // Only IPv4 traffic (from the host's UDP echo app). Ignore ARP, etc.
    if (protocol != 0x0800)
    {
        return;
    }

    std::string ip = ExtractIpv4Dst(packet);
    auto ipIt = m_ipToDst.find(ip);
    if (ipIt == m_ipToDst.end())
    {
        ++m_drops;
        ++m_dropFromHostNoIp;
        return;
    }
    uint32_t dst_node = ipIt->second;
    uint32_t arrival_ts = CurrentSlice();

    // Fast path: packet destined for a host directly attached to this ToR.
    // Shouldn't happen under typical topologies but handled for completeness.
    auto aadIt = m_arriveAtDst.find(dst_node);
    if (aadIt != m_arriveAtDst.end() && dst_node == m_torId)
    {
        Ptr<Packet> pkt = packet->Copy();
        if (m_hostDev)
        {
            m_hostDev->Send(pkt, m_hostDev->GetBroadcast(), protocol);
        }
        ++m_deliveredToHost;
        return;
    }

    // Source-routing has priority: if an SR entry exists for this
    // (dst, arrival_ts), stamp the hop list and dispatch. Otherwise
    // fall back to per-hop.
    if (TrySourceRoutingIngress(packet, dst_node, arrival_ts, protocol))
    {
        return;
    }

    // Prepend the OpenOptics header and route via per-hop table.
    Ptr<Packet> pkt = packet->Copy();
    OpenOpticsHeader hdr(dst_node, arrival_ts);
    pkt->AddHeader(hdr);
    HandleRoutedPacket(pkt, dst_node, arrival_ts, protocol);
}

void
TorApp::ReceiveFromUplink(Ptr<NetDevice> /*device*/,
                          Ptr<const Packet> packet,
                          uint16_t protocol,
                          const Address& /*src*/,
                          const Address& /*dst*/,
                          NetDevice::PacketType /*packetType*/)
{
    ++m_ingressFromUplink;

    // All uplink traffic carries an OpenOpticsHeader; its ``mode`` byte
    // distinguishes per-hop from source-routed. We tunnel under
    // ethertype 0x0800 to avoid fighting PointToPointNetDevice's PPP
    // framing, so anything else here is misconfig / stray control
    // traffic — drop before touching the body.
    if (protocol != 0x0800)
    {
        ++m_drops;
        ++m_dropFromUplinkProtocol;
        return;
    }
    Ptr<Packet> pkt = packet->Copy();
    OpenOpticsHeader hdr;
    if (pkt->GetSize() < hdr.GetSerializedSize())
    {
        ++m_drops;
        ++m_dropFromUplinkParse;
        return;
    }
    pkt->RemoveHeader(hdr);

    if (hdr.GetMode() == OpenOpticsHeader::kSourceRouted)
    {
        HandleSourceRoutedUplink(pkt, hdr, protocol);
        return;
    }

    uint32_t dst_node = hdr.GetDstNode();

    auto aadIt = m_arriveAtDst.find(dst_node);
    if (aadIt != m_arriveAtDst.end())
    {
        // Packet is at its destination — send to the host (no header).
        if (m_hostDev)
        {
            m_hostDev->Send(pkt, m_hostDev->GetBroadcast(), protocol);
        }
        ++m_deliveredToHost;
        return;
    }

    // Not at destination — re-route. arrival_ts is recomputed locally
    // since the upstream slice is stale after propagation through the OCS.
    uint32_t arrival_ts = CurrentSlice();
    // Re-stamp the header so the invariant "uplink traffic carries a
    // fresh OpenOpticsHeader" holds for downstream ToRs.
    OpenOpticsHeader fresh(dst_node, arrival_ts);
    pkt->AddHeader(fresh);
    HandleRoutedPacket(pkt, dst_node, arrival_ts, protocol);
}

void
TorApp::HandleRoutedPacket(Ptr<Packet> packet_with_header,
                           uint32_t dst_node,
                           uint32_t arrival_ts,
                           uint16_t protocol)
{
    // ADM mode: walk per-hop entries for (dst, arrival_ts + offset) and
    // forward on the first whose AdmCheck passes — each offset asks
    // "what would my plan be if I'd arrived k slots later", i.e. the
    // ToR decides to wait k slots before routing.
    if (m_admissionControl && m_numSlices > 0)
    {
        const std::size_t pkt_bytes = packet_with_header->GetSize();
        for (uint32_t offset = 0; offset < m_numSlices; ++offset)
        {
            const uint32_t try_ts = (arrival_ts + offset) % m_numSlices;
            const uint64_t k = PerHopKey(dst_node, try_ts);
            auto pIt = m_perHopSendPort.find(k);
            auto tIt = m_perHopSendTs.find(k);
            if (pIt == m_perHopSendPort.end() || tIt == m_perHopSendTs.end())
            {
                continue;
            }
            const uint32_t send_port = pIt->second;
            const uint32_t send_ts = tIt->second;
            if (send_port == 255 || send_ts == 255)
            {
                continue;
            }
            if (AdmCheck(send_ts, send_port, pkt_bytes))
            {
                ForwardOnSlice(packet_with_header, send_port, send_ts, protocol);
                return;
            }
        }
        // No slot at any offset can admit this packet — drop.
        ++m_drops;
        ++m_dropAdmFail;
        return;
    }

    uint64_t k = PerHopKey(dst_node, arrival_ts);
    auto portIt = m_perHopSendPort.find(k);
    auto tsIt = m_perHopSendTs.find(k);
    if (portIt == m_perHopSendPort.end() || tsIt == m_perHopSendTs.end())
    {
        ++m_drops;
        ++m_dropPerHopMissed;
        return;
    }

    uint32_t send_port = portIt->second;
    uint32_t send_ts = tsIt->second;

    // Per-hop entries don't use sentinels (source-routing does). Catch
    // a mis-populated table loudly rather than sending on port 255.
    if (send_port == 255 || send_ts == 255)
    {
        ++m_drops;
        ++m_dropPerHopSentinel;
        return;
    }

    ForwardOnSlice(packet_with_header, send_port, send_ts, protocol);
}

// Enqueue into the (uplink, send_ts) bucket and drain immediately if
// send_ts is the current slice. Total calendar-queue byte-buffer admission
// happens here; per-slice drain budget enforcement lives in DrainSlice +
// CanFinishInActiveWindow. Callers must have resolved any sentinels already.
void
TorApp::ForwardOnSlice(Ptr<Packet> pkt_with_headers,
                       uint32_t send_port,
                       uint32_t send_ts,
                       uint16_t /*protocol*/)
{
    // protocol is unused — every uplink-bound frame goes out as 0x0800
    // (the only ethertype this app handles). Kept in the signature to
    // match ns-3's protocol-handler convention.
    if (send_port >= m_uplinks.size())
    {
        ++m_drops;
        ++m_dropForwardPort;
        return;
    }

    const std::size_t pkt_bytes = pkt_with_headers->GetSize();
    const uint64_t pkt_bytes_u64 = static_cast<uint64_t>(pkt_bytes);
    if (pkt_bytes_u64 > m_cqBufferCapacityBytes ||
        m_cqBufferedBytes > m_cqBufferCapacityBytes - pkt_bytes_u64)
    {
        ++m_drops;
        ++m_dropForwardCq;
        return;
    }
    if (!m_cq[send_port].Enqueue(send_ts, pkt_with_headers, /*cookie=*/0))
    {
        // Invalid slice id. CalendarQueue tracks this internally too;
        // mirroring into m_drops keeps tests checking one place.
        ++m_drops;
        ++m_dropForwardCq;
        return;
    }
    m_cqBufferedBytes += pkt_bytes_u64;
    if (m_cqBufferedBytes > m_cqPeakBufferedBytes)
    {
        m_cqPeakBufferedBytes = m_cqBufferedBytes;
    }
    // Mirror byte tracker, keyed by (slot, egress uplink).
    if (send_ts < m_cqBytesPerSlot.size() &&
        send_port < m_cqBytesPerSlot[send_ts].size())
    {
        m_cqBytesPerSlot[send_ts][send_port] += pkt_bytes_u64;
    }
    // Same-slice arrival: OnSliceBoundary for this slot already fired,
    // so without an immediate drain the packet would sit until the slot
    // recurs next cycle. DrainSlice handles admission + late-rollover.
    if (send_ts == CurrentSlice())
    {
        DrainSlice(send_ts);
    }
}

// Resolve a (possibly-sentineled) hop into (send_port, send_ts).
// Three patterns:
//   - Plain port-type:  ts < 255, port < 255           → pass through
//   - Node-type:        ts == 255, port_or_node < 255  → look up
//                        cal_port_slice_to_node((port_or_node, arrival_ts))
//   - Random VLB:       ts == 255, port_or_node == 255 → uniform-random
//                        uplink at CurrentSlice
// Returns false (and bumps m_drops) on resolution failure.
bool
TorApp::ResolveHop(const OpenOpticsSourceRouteHeader::Hop& hop,
                   uint32_t arrival_ts,
                   uint32_t* out_send_port,
                   uint32_t* out_send_ts)
{
    if (hop.send_ts != 255 && hop.send_port_or_node != 255)
    {
        // Plain port-type hop.
        *out_send_port = hop.send_port_or_node;
        *out_send_ts = hop.send_ts;
        return true;
    }

    if (hop.send_ts == 255 && hop.send_port_or_node == 255)
    {
        // Random-port VLB: pick a uniform-random uplink, send in the
        // current slice.
        if (m_uplinks.empty())
        {
            ++m_drops;
            ++m_dropResolveRandom;
            return false;
        }
        if (!m_rng)
        {
            m_rng = CreateObject<UniformRandomVariable>();
        }
        const uint32_t rnd =
            m_rng->GetInteger(0, static_cast<uint32_t>(m_uplinks.size() - 1));
        *out_send_port = rnd;
        *out_send_ts = CurrentSlice();
        return true;
    }

    if (hop.send_ts == 255 && hop.send_port_or_node != 255)
    {
        // Node-type hop. send_port_or_node is a destination node id;
        // consult cal_port_slice_to_node keyed on (node_dst, arrival_ts).
        const uint64_t k = PerHopKey(hop.send_port_or_node, arrival_ts);
        auto portIt = m_calSendPort.find(k);
        auto tsIt = m_calSendTs.find(k);
        if (portIt == m_calSendPort.end() || tsIt == m_calSendTs.end())
        {
            ++m_drops;
            ++m_dropResolveNode;
            return false;
        }
        *out_send_port = portIt->second;
        *out_send_ts = tsIt->second;
        return true;
    }

    // ts < 255, port == 255: not a pattern the routing algorithms
    // produce. Drop defensively.
    ++m_drops;
    ++m_dropResolveFallthrough;
    return false;
}

// Host-ingress source routing: stamp SR + OpenOptics headers and
// dispatch the first hop. Returns true if dispatched (caller must NOT
// fall through to per-hop), false if no SR entry matched.
bool
TorApp::TrySourceRoutingIngress(Ptr<const Packet> raw_ip_packet,
                                uint32_t dst_node,
                                uint32_t arrival_ts,
                                uint16_t /*host_protocol*/)
{
    auto it = m_sourceRouting.find(PerHopKey(dst_node, arrival_ts));
    if (it == m_sourceRouting.end())
    {
        return false;
    }
    const std::vector<OpenOpticsSourceRouteHeader::Hop>& hops = it->second;
    if (hops.empty())
    {
        ++m_drops;
        ++m_dropSrEmpty;
        return true;   // handled (dropped) — do not fall through
    }

    // Optional P4-style verify_desired_node gate. Trivially true at
    // ingress in normal cases, but keeping it symmetric with the
    // transit path catches a misprogrammed routing table loudly.
    if (m_verifySrCurNode && !HopBelongsHere(hops[0].cur_node, m_torId))
    {
        ++m_drops;
        ++m_dropSrIngressBadCur;
        return true;
    }

    // Resolve hop 0 before stamping so a random-port pick lands in the
    // header we put on the wire (downstream ToRs use current_idx > 0).
    uint32_t send_port = 0;
    uint32_t send_ts = 0;
    if (!ResolveHop(hops[0], arrival_ts, &send_port, &send_ts))
    {
        return true;   // drop already counted in ResolveHop
    }

    // Stamp hops with current_idx=1 so the next ToR picks up hops[1].
    // Wire format: [OpenOpticsHeader(mode=SR)][SR][payload] — add SR
    // first (innermost) so peeling OO at the receiver exposes the mode.
    Ptr<Packet> pkt = raw_ip_packet->Copy();

    OpenOpticsSourceRouteHeader sr(hops);
    sr.SetCurrentIdx(1);
    pkt->AddHeader(sr);

    OpenOpticsHeader oo(dst_node, arrival_ts);
    oo.SetMode(OpenOpticsHeader::kSourceRouted);
    pkt->AddHeader(oo);

    ForwardOnSlice(pkt, send_port, send_ts, /*protocol=*/0x0800);
    return true;
}

void
TorApp::HandleSourceRoutedUplink(Ptr<Packet> pkt_without_oo_header,
                                 const OpenOpticsHeader& oo,
                                 uint16_t /*carried_protocol*/)
{
    // ReceiveFromUplink already peeled OpenOpticsHeader (it needed
    // ``mode`` to branch here). Now peel the inner SR header.
    OpenOpticsSourceRouteHeader sr;
    if (pkt_without_oo_header->GetSize() < sr.GetSerializedSize())
    {
        ++m_drops;
        ++m_dropSrUplinkSize;
        return;
    }
    pkt_without_oo_header->RemoveHeader(sr);

    const uint32_t dst_node = oo.GetDstNode();
    const uint32_t arrival_ts = CurrentSlice();
    const uint8_t idx = sr.GetCurrentIdx();
    const uint8_t n_hops = sr.GetHopCount();

    // All hops consumed → deliver to host (if arrive_at_dst matches).
    if (idx >= n_hops)
    {
        auto it = m_arriveAtDst.find(dst_node);
        if (it == m_arriveAtDst.end())
        {
            ++m_drops;
            ++m_dropSrEndNotDst;
            return;
        }
        if (m_hostDev)
        {
            // Raw IP payload back out to the attached host.
            m_hostDev->Send(pkt_without_oo_header,
                            m_hostDev->GetBroadcast(), 0x0800);
        }
        ++m_deliveredToHost;
        return;
    }

    // Optional P4-style verify_desired_node gate.
    const auto& hop = sr.GetHopAt(idx);
    if (m_verifySrCurNode && !HopBelongsHere(hop.cur_node, m_torId))
    {
        ++m_drops;
        ++m_dropSrTransitBadCur;
        return;
    }

    // Still hops to run — resolve, advance the cursor, re-stamp
    // [OO][SR] (SR innermost), and forward.
    uint32_t send_port = 0;
    uint32_t send_ts = 0;
    if (!ResolveHop(hop, arrival_ts, &send_port, &send_ts))
    {
        return;
    }
    sr.IncrementCurrentIdx();
    pkt_without_oo_header->AddHeader(sr);
    // Re-stamp OO with SR mode so the next ToR keeps peeling SR.
    OpenOpticsHeader fresh_oo(dst_node, arrival_ts);
    fresh_oo.SetMode(OpenOpticsHeader::kSourceRouted);
    pkt_without_oo_header->AddHeader(fresh_oo);
    ForwardOnSlice(pkt_without_oo_header, send_port, send_ts,
                   /*protocol=*/0x0800);
}

} // namespace openoptics
} // namespace ns3
