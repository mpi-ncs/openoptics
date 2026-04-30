"""ns-3 version of mininet_routing_hoho_source.py.

Opera topology + HoHo multi-hop paths, source-routed end to end. The
ingress ToR stamps the full 2-hop path; the intermediate ToR consumes hop
0, forwards to the final OCS→destination uplink; the destination peels
both headers and delivers.

Contrast with ns3_routing_hoho_perhop.py — same topology and routing
algorithm, but the intermediate ToR relies on the source-route header
rather than its own per_hop_routing table to make the forwarding decision.
Useful for comparing the two modes under the same workload.
"""

from openoptics import Toolbox, OpticalTopo, OpticalRouting

if __name__ == "__main__":
    nb_node = 4
    nb_link = 1
    net = Toolbox.BaseNetwork(
        name="ns3_routing_hoho_source",
        backend="ns3",
        nb_node=nb_node,
        nb_link=nb_link,
        time_slice_duration_us=10_000,
        guardband_ms=0,
        ocs_tor_link_bw_gbps=100,
        tor_host_link_bw_gbps=100,
        use_webserver=True,
        simulation_stop_s=1.0,
    )
    circuits = OpticalTopo.opera(nb_node=nb_node, nb_link=nb_link)
    assert net.deploy_topo(circuits)
    paths = OpticalRouting.routing_hoho(net.get_topo())
    assert net.deploy_routing(paths, routing_mode="Source")

    net.udp_traffic() \
        .echo(0, 2, start_s=0.05, stop_s=0.8,
              num_packets=20, interval_s=0.03) \
        .install()
    net.start()
