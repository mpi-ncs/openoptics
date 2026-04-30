// Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
// Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
//
// Author: Yiming Lei (ylei@mpi-inf.mpg.de)
//
// License: Creative Commons NC BY SA 4.0
// https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en

#include "openoptics-ocs-app.h"

#include "ns3/log.h"
#include "ns3/node.h"
#include "ns3/simulator.h"

namespace ns3
{
namespace openoptics
{

NS_LOG_COMPONENT_DEFINE("OpenOpticsOcs");
NS_OBJECT_ENSURE_REGISTERED(OcsApp);

TypeId
OcsApp::GetTypeId()
{
    static TypeId tid =
        TypeId("ns3::openoptics::OcsApp")
            .SetParent<Application>()
            .SetGroupName("OpenOptics")
            .AddConstructor<OcsApp>()
            .AddTraceSource("Snapshot",
                            "Periodic aggregate counters (sim_time_us, "
                            "forward_count, drop_count).",
                            MakeTraceSourceAccessor(&OcsApp::m_snapshotTrace),
                            "ns3::openoptics::OcsApp::SnapshotCallback");
    return tid;
}

OcsApp::OcsApp()
    : m_sliceDurationUs(0),
      m_numSlices(0),
      m_guardbandUs(0),
      m_forwardCount(0),
      m_dropCount(0),
      m_started(false),
      m_snapshotInterval(Seconds(0))
{
}

OcsApp::~OcsApp() = default;

uint32_t
OcsApp::AddPort(Ptr<NetDevice> device)
{
    NS_ASSERT_MSG(GetNode() != nullptr,
                  "AddPort called before the app was added to a node");
    uint32_t port = m_ports.size();
    m_ports.push_back(device);
    m_portIndex[device] = port;

    // protocol=0 + promiscuous: handler fires on every ethertype.
    GetNode()->RegisterProtocolHandler(
        MakeCallback(&OcsApp::ReceiveFromPort, this),
        /*protocol=*/0,
        device,
        /*promiscuous=*/true);
    return port;
}

void
OcsApp::SetSliceDurationUs(uint64_t us)
{
    m_sliceDurationUs = us;
}

void
OcsApp::SetNumSlices(uint32_t n)
{
    m_numSlices = n;
}

void
OcsApp::SetGuardbandUs(uint64_t us)
{
    m_guardbandUs = us;
}

uint64_t
OcsApp::MakeKey(uint32_t ingress_port, uint32_t slice)
{
    return (static_cast<uint64_t>(ingress_port) << 32) | slice;
}

void
OcsApp::AddScheduleEntry(uint32_t ingress_port, uint32_t slice, uint32_t egress_port)
{
    m_schedule[MakeKey(ingress_port, slice)] = egress_port;
}

void
OcsApp::ClearSchedule()
{
    m_schedule.clear();
}

uint64_t
OcsApp::GetForwardCount() const
{
    return m_forwardCount;
}

uint64_t
OcsApp::GetDropCount() const
{
    return m_dropCount;
}

std::size_t
OcsApp::GetScheduleEntryCount() const
{
    return m_schedule.size();
}

uint32_t
OcsApp::LookupSchedule(uint32_t ingress_port, uint32_t slice) const
{
    auto it = m_schedule.find(MakeKey(ingress_port, slice));
    if (it == m_schedule.end())
    {
        return UINT32_MAX;
    }
    return it->second;
}

uint32_t
OcsApp::CurrentSlice() const
{
    if (m_sliceDurationUs == 0 || m_numSlices == 0)
    {
        return 0;
    }
    uint64_t now = Simulator::Now().GetMicroSeconds();
    return static_cast<uint32_t>((now / m_sliceDurationUs) % m_numSlices);
}

void
OcsApp::StartApplication()
{
    m_started = true;
}

void
OcsApp::StopApplication()
{
    m_started = false;
    if (m_snapshotEvent.IsPending())
    {
        Simulator::Cancel(m_snapshotEvent);
    }
}

void
OcsApp::ScheduleSnapshots(Time interval)
{
    m_snapshotInterval = interval;
    // Fire once immediately (t=now snapshot), then self-reschedule.
    EmitSnapshot();
}

void
OcsApp::SetSnapshotListener(OcsApp::SnapshotListener fn)
{
    m_snapshotListener = std::move(fn);
}

void
OcsApp::EmitSnapshot()
{
    const uint64_t t = static_cast<uint64_t>(Simulator::Now().GetMicroSeconds());
    m_snapshotTrace(t, m_forwardCount, m_dropCount);
    if (m_snapshotListener)
    {
        m_snapshotListener(t, m_forwardCount, m_dropCount);
    }
    m_snapshotEvent =
        Simulator::Schedule(m_snapshotInterval, &OcsApp::EmitSnapshot, this);
}

void
OcsApp::ReceiveFromPort(Ptr<NetDevice> device,
                        Ptr<const Packet> packet,
                        uint16_t protocol,
                        const Address& src,
                        const Address& dst,
                        NetDevice::PacketType /*packetType*/)
{
    auto portIt = m_portIndex.find(device);
    if (portIt == m_portIndex.end())
    {
        // Shouldn't happen — handlers only register for added ports.
        ++m_dropCount;
        return;
    }

    // Dark-window: drop if we land inside the slice's tail guardband
    // (when the OCS would be reconfiguring). No-op for guardband == 0.
    if (m_guardbandUs > 0 && m_sliceDurationUs > 0)
    {
        uint64_t now_us = Simulator::Now().GetMicroSeconds();
        uint64_t offset = now_us % m_sliceDurationUs;
        if (offset + m_guardbandUs >= m_sliceDurationUs)
        {
            ++m_dropCount;
            return;
        }
    }

    uint32_t in_port = portIt->second;
    uint32_t slice = CurrentSlice();

    auto schedIt = m_schedule.find(MakeKey(in_port, slice));
    if (schedIt == m_schedule.end())
    {
        ++m_dropCount;
        return;
    }
    uint32_t out_port = schedIt->second;
    if (out_port >= m_ports.size())
    {
        ++m_dropCount;
        return;
    }

    Ptr<NetDevice> outDev = m_ports[out_port];
    // The OCS has no MAC concept. Pass the packet through with its
    // original dst (P2P ignores the address internally).
    outDev->Send(packet->Copy(), dst, protocol);
    ++m_forwardCount;
}

} // namespace openoptics
} // namespace ns3
