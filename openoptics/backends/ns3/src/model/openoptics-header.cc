// Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
// Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
//
// Author: Yiming Lei (ylei@mpi-inf.mpg.de)
//
// License: Creative Commons NC BY SA 4.0
// https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en

#include "openoptics-header.h"

namespace ns3
{
namespace openoptics
{

NS_OBJECT_ENSURE_REGISTERED(OpenOpticsHeader);

TypeId
OpenOpticsHeader::GetTypeId()
{
    static TypeId tid = TypeId("ns3::openoptics::OpenOpticsHeader")
                            .SetParent<Header>()
                            .SetGroupName("OpenOptics")
                            .AddConstructor<OpenOpticsHeader>();
    return tid;
}

TypeId
OpenOpticsHeader::GetInstanceTypeId() const
{
    return GetTypeId();
}

OpenOpticsHeader::OpenOpticsHeader()
    : m_mode(kPerHop),
      m_dstNode(0),
      m_arrivalTs(0)
{
}

OpenOpticsHeader::OpenOpticsHeader(uint32_t dst_node, uint32_t arrival_ts)
    : m_mode(kPerHop),
      m_dstNode(dst_node),
      m_arrivalTs(arrival_ts)
{
}

uint32_t OpenOpticsHeader::GetDstNode() const       { return m_dstNode; }
uint32_t OpenOpticsHeader::GetArrivalTs() const     { return m_arrivalTs; }
OpenOpticsHeader::Mode OpenOpticsHeader::GetMode() const
{
    return static_cast<Mode>(m_mode);
}

void OpenOpticsHeader::SetDstNode(uint32_t dst)     { m_dstNode = dst; }
void OpenOpticsHeader::SetArrivalTs(uint32_t ts)    { m_arrivalTs = ts; }
void OpenOpticsHeader::SetMode(Mode m)              { m_mode = static_cast<uint8_t>(m); }

uint32_t
OpenOpticsHeader::GetSerializedSize() const
{
    // [mode:1] [reserved:3] [dst_node:4] [arrival_ts:4]
    return 12;
}

void
OpenOpticsHeader::Serialize(Buffer::Iterator start) const
{
    start.WriteU8(m_mode);
    start.WriteU8(0);     // reserved
    start.WriteU8(0);
    start.WriteU8(0);
    start.WriteHtonU32(m_dstNode);
    start.WriteHtonU32(m_arrivalTs);
}

uint32_t
OpenOpticsHeader::Deserialize(Buffer::Iterator start)
{
    m_mode = start.ReadU8();
    start.ReadU8();       // reserved
    start.ReadU8();
    start.ReadU8();
    m_dstNode = start.ReadNtohU32();
    m_arrivalTs = start.ReadNtohU32();
    return GetSerializedSize();
}

void
OpenOpticsHeader::Print(std::ostream& os) const
{
    os << "OpenOptics mode=" << (int)m_mode
       << " dst=" << m_dstNode
       << " arrival_ts=" << m_arrivalTs;
}

} // namespace openoptics
} // namespace ns3
