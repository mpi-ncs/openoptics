// Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
// Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
//
// Author: Yiming Lei (ylei@mpi-inf.mpg.de)
//
// License: Creative Commons NC BY SA 4.0
// https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en

#ifndef OPENOPTICS_HEADER_H
#define OPENOPTICS_HEADER_H

#include "ns3/header.h"

#include <cstdint>

namespace ns3
{
namespace openoptics
{

// Small L3-over-L2 header carried between OpenOptics ToRs.
// dst_node: logical destination ToR id (set by the ingress ToR from ip_to_dst_node).
// arrival_ts: slice index at which the packet entered the current ToR; used as a
// match key in per_hop_routing.
//
// Also carries a ``mode`` byte so uplink-ingress code can branch between
// the per-hop and source-routed forwarding paths. In source-routed mode,
// an OpenOpticsSourceRouteHeader follows directly behind this header.
// Wire format (all fields big-endian, total 12 bytes):
//     [mode:1] [reserved:3] [dst_node:4] [arrival_ts:4]
//
// We keep OpenOpticsHeader at a fixed 12 bytes regardless of mode to
// avoid branching in the parser. The underlying PPP framing on
// PointToPointNetDevice only accepts 0x0800 / 0x86DD ethertypes, so we
// can't distinguish per-hop from SR via a separate ethertype; the mode
// byte is our in-band marker.
class OpenOpticsHeader : public Header
{
  public:
    enum Mode : uint8_t
    {
        kPerHop = 0,
        kSourceRouted = 1,
    };

    OpenOpticsHeader();
    OpenOpticsHeader(uint32_t dst_node, uint32_t arrival_ts);

    static TypeId GetTypeId();
    TypeId GetInstanceTypeId() const override;

    uint32_t GetDstNode() const;
    uint32_t GetArrivalTs() const;
    Mode GetMode() const;

    void SetDstNode(uint32_t dst);
    void SetArrivalTs(uint32_t ts);
    void SetMode(Mode m);

    uint32_t GetSerializedSize() const override;
    void Serialize(Buffer::Iterator start) const override;
    uint32_t Deserialize(Buffer::Iterator start) override;
    void Print(std::ostream& os) const override;

  private:
    uint8_t m_mode;
    uint32_t m_dstNode;
    uint32_t m_arrivalTs;
};

} // namespace openoptics
} // namespace ns3

#endif // OPENOPTICS_HEADER_H
