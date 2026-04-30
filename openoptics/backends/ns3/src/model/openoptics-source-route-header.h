// Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
// Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
//
// Author: Yiming Lei (ylei@mpi-inf.mpg.de)
//
// License: Creative Commons NC BY SA 4.0
// https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en

#ifndef OPENOPTICS_SOURCE_ROUTE_HEADER_H
#define OPENOPTICS_SOURCE_ROUTE_HEADER_H

#include "ns3/header.h"

#include <cstdint>
#include <vector>

namespace ns3
{
namespace openoptics
{

// Source-routing header: ingress ToR stamps the full hop list, each
// downstream ToR consumes one entry. Hops mirror the 3-tuple from
// ``utils.tor_table_routing_source`` — ``(cur_node, send_ts,
// send_port_or_node)``:
//   * ``cur_node``: expected current-node id; 255 = wildcard (VLB's
//     random intermediate hop).
//   * ``send_ts``: send slice; 255 = "node-type" — resolve at runtime
//     via cal_port_slice_to_node.
//   * ``send_port_or_node``: uplink index when ``send_ts != 255``,
//     destination node id when ``send_ts == 255``. The extra sentinel
//     ``port_or_node == 255 && ts == 255`` means "random-port dispatch
//     in the current slice" (routing_vlb(random=True)).
//
// On-wire (big-endian):
//   [hop_count : u8] [current_idx : u8] [hops : hop_count * 12 B]
// Each hop is three u32s.
//
// Distinguished from per-hop traffic by the OpenOpticsHeader ``mode``
// byte, not ethertype — PPP framing forces all uplink traffic to 0x0800.
class OpenOpticsSourceRouteHeader : public Header
{
  public:
    // Plain struct (not an ns-3 type) — trivial across the cppyy boundary.
    struct Hop
    {
        uint32_t cur_node;
        uint32_t send_ts;
        uint32_t send_port_or_node;
    };

    OpenOpticsSourceRouteHeader();
    explicit OpenOpticsSourceRouteHeader(std::vector<Hop> hops);

    static TypeId GetTypeId();
    TypeId GetInstanceTypeId() const override;

    uint8_t GetHopCount() const;
    uint8_t GetCurrentIdx() const;
    const Hop& GetHopAt(uint8_t idx) const;
    void SetCurrentIdx(uint8_t idx);
    void IncrementCurrentIdx();

    uint32_t GetSerializedSize() const override;
    void Serialize(Buffer::Iterator start) const override;
    uint32_t Deserialize(Buffer::Iterator start) override;
    void Print(std::ostream& os) const override;

  private:
    // 16-hop ceiling — 4× the Mininet P4 impl and plenty for current
    // routing algorithms.
    static constexpr uint8_t kMaxHops = 16;

    uint8_t m_currentIdx;
    std::vector<Hop> m_hops;
};

} // namespace openoptics
} // namespace ns3

#endif // OPENOPTICS_SOURCE_ROUTE_HEADER_H
