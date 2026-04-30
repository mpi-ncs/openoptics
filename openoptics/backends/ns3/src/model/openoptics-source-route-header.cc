// Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
// Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
//
// Author: Yiming Lei (ylei@mpi-inf.mpg.de)
//
// License: Creative Commons NC BY SA 4.0
// https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en

#include "openoptics-source-route-header.h"

#include "ns3/fatal-error.h"

namespace ns3
{
namespace openoptics
{

NS_OBJECT_ENSURE_REGISTERED(OpenOpticsSourceRouteHeader);

TypeId
OpenOpticsSourceRouteHeader::GetTypeId()
{
    static TypeId tid = TypeId("ns3::openoptics::OpenOpticsSourceRouteHeader")
                            .SetParent<Header>()
                            .SetGroupName("OpenOptics")
                            .AddConstructor<OpenOpticsSourceRouteHeader>();
    return tid;
}

TypeId
OpenOpticsSourceRouteHeader::GetInstanceTypeId() const
{
    return GetTypeId();
}

OpenOpticsSourceRouteHeader::OpenOpticsSourceRouteHeader()
    : m_currentIdx(0)
{
}

OpenOpticsSourceRouteHeader::OpenOpticsSourceRouteHeader(std::vector<Hop> hops)
    : m_currentIdx(0),
      m_hops(std::move(hops))
{
    if (m_hops.size() > kMaxHops)
    {
        NS_FATAL_ERROR("OpenOpticsSourceRouteHeader: hop_count "
                       << m_hops.size() << " exceeds cap " << (int)kMaxHops);
    }
}

uint8_t
OpenOpticsSourceRouteHeader::GetHopCount() const
{
    return static_cast<uint8_t>(m_hops.size());
}

uint8_t
OpenOpticsSourceRouteHeader::GetCurrentIdx() const
{
    return m_currentIdx;
}

const OpenOpticsSourceRouteHeader::Hop&
OpenOpticsSourceRouteHeader::GetHopAt(uint8_t idx) const
{
    if (idx >= m_hops.size())
    {
        NS_FATAL_ERROR("GetHopAt(" << (int)idx << ") out of range; hop_count="
                       << m_hops.size());
    }
    return m_hops[idx];
}

void
OpenOpticsSourceRouteHeader::SetCurrentIdx(uint8_t idx)
{
    m_currentIdx = idx;
}

void
OpenOpticsSourceRouteHeader::IncrementCurrentIdx()
{
    ++m_currentIdx;
}

uint32_t
OpenOpticsSourceRouteHeader::GetSerializedSize() const
{
    // [hop_count:1][current_idx:1] + hop_count * 12 (three u32 per hop).
    return 2 + static_cast<uint32_t>(m_hops.size()) * 12;
}

void
OpenOpticsSourceRouteHeader::Serialize(Buffer::Iterator start) const
{
    start.WriteU8(GetHopCount());
    start.WriteU8(m_currentIdx);
    for (const Hop& h : m_hops)
    {
        start.WriteHtonU32(h.cur_node);
        start.WriteHtonU32(h.send_ts);
        start.WriteHtonU32(h.send_port_or_node);
    }
}

uint32_t
OpenOpticsSourceRouteHeader::Deserialize(Buffer::Iterator start)
{
    const uint8_t hop_count = start.ReadU8();
    m_currentIdx = start.ReadU8();
    if (hop_count > kMaxHops)
    {
        NS_FATAL_ERROR("Deserialized hop_count " << (int)hop_count
                       << " exceeds cap " << (int)kMaxHops);
    }
    m_hops.clear();
    m_hops.reserve(hop_count);
    for (uint8_t i = 0; i < hop_count; ++i)
    {
        Hop h;
        h.cur_node = start.ReadNtohU32();
        h.send_ts = start.ReadNtohU32();
        h.send_port_or_node = start.ReadNtohU32();
        m_hops.push_back(h);
    }
    return GetSerializedSize();
}

void
OpenOpticsSourceRouteHeader::Print(std::ostream& os) const
{
    os << "OpenOpticsSR hops=" << m_hops.size()
       << " idx=" << (int)m_currentIdx;
    for (std::size_t i = 0; i < m_hops.size(); ++i)
    {
        os << " [" << i << ":(" << m_hops[i].cur_node << ','
           << m_hops[i].send_ts << ',' << m_hops[i].send_port_or_node << ")]";
    }
}

} // namespace openoptics
} // namespace ns3
