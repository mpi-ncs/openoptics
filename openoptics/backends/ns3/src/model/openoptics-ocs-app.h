// Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
// Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
//
// Author: Yiming Lei (ylei@mpi-inf.mpg.de)
//
// License: Creative Commons NC BY SA 4.0
// https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en

#ifndef OPENOPTICS_OCS_APP_H
#define OPENOPTICS_OCS_APP_H

#include "ns3/application.h"
#include "ns3/callback.h"
#include "ns3/event-id.h"
#include "ns3/net-device.h"
#include "ns3/nstime.h"
#include "ns3/packet.h"
#include "ns3/ptr.h"
#include "ns3/traced-callback.h"

#include <cstdint>
#include <functional>
#include <unordered_map>
#include <vector>

namespace ns3
{
namespace openoptics
{

// Optical circuit switch: stateless, time-gated packet forwarding.
//
// Implemented as an Application (not a NetDevice) because
// PointToPointNetDevice lacks SendFrom — required for bridge-style
// NetDevice forwarding. Application + RegisterProtocolHandler gives
// the same L2 interception without fighting the P2P MAC model.
class OcsApp : public Application
{
  public:
    OcsApp();
    ~OcsApp() override;

    static TypeId GetTypeId();

    // Register ``device`` as the next port and route its incoming
    // packets through ReceiveFromPort. Must be called after the OcsApp
    // is added to a node — handler registration needs one.
    uint32_t AddPort(Ptr<NetDevice> device);

    // Configure the slice clock. Both must be called before traffic starts.
    void SetSliceDurationUs(uint64_t us);
    void SetNumSlices(uint32_t n);

    // Dark window at the slice tail, in µs. Packets arriving in this
    // window are dropped (models OCS mirror reconfiguration time).
    // Default 0.
    void SetGuardbandUs(uint64_t us);

    // Schedule-table programming (called from Python load_table()).
    void AddScheduleEntry(uint32_t ingress_port, uint32_t slice, uint32_t egress_port);
    void ClearSchedule();

    // Introspection (counters + state for tests).
    uint64_t GetForwardCount() const;
    uint64_t GetDropCount() const;
    std::size_t GetScheduleEntryCount() const;
    // Egress port for (ingress_port, slice), or UINT32_MAX if missing.
    // Lets tests inspect the LUT without injecting packets.
    uint32_t LookupSchedule(uint32_t ingress_port, uint32_t slice) const;

    // Schedule periodic snapshot emission every ``interval``; cancelled
    // on StopApplication.
    void ScheduleSnapshots(Time interval);

    // std::function listener for the Python dashboard sink (cppyy can't
    // bind Python callables via MakeCallback). Fires alongside
    // m_snapshotTrace, so C++ TraceConnect consumers still work.
    using SnapshotListener =
        std::function<void(uint64_t /*sim_time_us*/,
                           uint64_t /*forward_count*/,
                           uint64_t /*drop_count*/)>;
    void SetSnapshotListener(SnapshotListener fn);

  protected:
    void StartApplication() override;
    void StopApplication() override;

  private:
    void ReceiveFromPort(Ptr<NetDevice> device,
                         Ptr<const Packet> packet,
                         uint16_t protocol,
                         const Address& src,
                         const Address& dst,
                         NetDevice::PacketType packetType);

    uint32_t CurrentSlice() const;

    // Fires m_snapshotTrace and re-schedules itself every m_snapshotInterval.
    void EmitSnapshot();

    // 64-bit composite (ingress_port, slice) — avoids a custom
    // std::hash for a pair, and keeps cppyy happy.
    static uint64_t MakeKey(uint32_t ingress_port, uint32_t slice);

    std::vector<Ptr<NetDevice>> m_ports;
    std::unordered_map<Ptr<NetDevice>, uint32_t> m_portIndex;
    std::unordered_map<uint64_t, uint32_t> m_schedule;

    uint64_t m_sliceDurationUs;
    uint32_t m_numSlices;
    uint64_t m_guardbandUs;

    uint64_t m_forwardCount;
    uint64_t m_dropCount;

    bool m_started;

    // Periodic snapshot state.
    Time m_snapshotInterval;
    EventId m_snapshotEvent;
    // Payload: (sim_time_us, forward_count, drop_count). C++ consumers
    // connect via TraceConnectWithoutContext("Snapshot", ...).
    TracedCallback<uint64_t, uint64_t, uint64_t> m_snapshotTrace;
    SnapshotListener m_snapshotListener;
};

} // namespace openoptics
} // namespace ns3

#endif // OPENOPTICS_OCS_APP_H
