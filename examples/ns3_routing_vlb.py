"""ns-3 version of mininet_routing_vlb.py.

Valiant Load Balancing. For every (src, dst) pair where no direct circuit
exists in slice ``ts``, the source ToR picks a deterministic intermediate
uplink and sends a 2-hop source-routed packet. The intermediate ToR's
second hop is encoded as a **node-type** sentinel ``(send_ts=255,
send_port_or_node=dst)``; at runtime the intermediate resolves that to a
concrete ``(send_port, send_ts)`` via its ``cal_port_slice_to_node`` table
— which the backend now populates (previously ignored).

With ``random=False`` (the default used here), the intermediate selection
is deterministic per ``ts``. For the randomised variant see
``ns3_routing_vlb_random.py``.
"""

from openoptics import Toolbox, OpticalTopo, OpticalRouting

if __name__ == "__main__":
    nb_node = 4
    net = Toolbox.BaseNetwork(
        name="ns3_routing_vlb",
        backend="ns3",
        nb_node=nb_node,
        time_slice_duration_us=10_000,
        guardband_ms=0,
        ocs_tor_link_bw_gbps=100,
        tor_host_link_bw_gbps=100,
        use_webserver=True,
        simulation_stop_s=1.0,
    )
    circuits = OpticalTopo.round_robin(nb_node=nb_node)
    assert net.deploy_topo(circuits)
    paths = OpticalRouting.routing_vlb(net.get_topo(), net.tor_ocs_ports)
    assert net.deploy_routing(paths, routing_mode="Source")

    # h0 -> h2: no direct (0,2) circuit in round_robin(4), so traffic takes
    # a 2-hop VLB path. Post-run report's per-tor counters will show the
    # intermediate hop picking up ingress_from_uplink=n and forwarding it.
    net.udp_traffic() \
        .echo(0, 2, start_s=0.05, stop_s=0.8,
              num_packets=20, interval_s=0.03) \
        .install()
    net.start()
