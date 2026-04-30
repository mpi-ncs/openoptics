"""ns-3 version of mininet_routing_direct_source.py.

4-ToR round-robin topology with 1-hop direct paths, but routing_mode="Source":
the ingress ToR stamps the complete hop list into an OpenOptics source-route
header; the destination ToR peels the header and delivers. No per_hop_routing
lookup at any intermediate (there are none in a 1-hop path anyway, but the
source-route code path is still exercised).

Compared to ns3_routing_direct_perhop.py the visible effect is that
tor_apps[i].GetPerHopEntryCount() is 0 — source routing installs entries in
`add_source_routing_entries` instead.

Dashboard snapshots run at sub-slice cadence, and the traffic start phase plus
1 ms burst interval are chosen so h0->h1 packets build up in the source-routed
calendar queue before their direct slice opens.
"""

from openoptics import Toolbox, OpticalTopo, OpticalRouting

if __name__ == "__main__":
    nb_node = 4
    net = Toolbox.BaseNetwork(
        name="ns3_routing_direct_source",
        backend="ns3",
        nb_node=nb_node,
        time_slice_duration_us=10_000,
        snapshot_interval_us=1_000,
        guardband_ms=0,
        ocs_tor_link_bw_gbps=100,
        tor_host_link_bw_gbps=100,
        use_webserver=True,
        simulation_stop_s=1.0,
    )
    circuits = OpticalTopo.round_robin(nb_node=nb_node)
    assert net.deploy_topo(circuits)
    paths = OpticalRouting.routing_direct(net.get_topo())
    net.deploy_routing(paths, routing_mode="Source")

    net.udp_traffic() \
        .echo(0, 1, start_s=0.045, stop_s=0.8,
              num_packets=200, interval_s=0.001) \
        .install()
    net.start()
