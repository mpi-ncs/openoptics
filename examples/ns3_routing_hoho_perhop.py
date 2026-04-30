"""ns-3 version of mininet_routing_hoho_per_hop.py.

Opera-style topology with multi-hop HoHo routing (up to 2 hops). The per-
hop mode means each ToR independently looks up its own next hop against
the ``per_hop_routing`` table; our TorApp's uplink-ingress path re-stamps
the OpenOpticsHeader and re-routes, which is exactly what HoHo needs for
intermediate hops.

HoHo's output doesn't use sentinel send_ts / send_port values in this
topology (verified via ``path2entries`` inspection during M4 development),
so the M1 ns-3 backend handles it natively.
"""

from openoptics import Toolbox, OpticalTopo, OpticalRouting

if __name__ == "__main__":
    nb_node = 8
    nb_link = 2
    net = Toolbox.BaseNetwork(
        name="ns3_routing_hoho_perhop",
        backend="ns3",
        nb_node=nb_node,
        nb_link=nb_link,
        time_slice_duration_us=10_000,     # 10 ms per slice
        guardband_ms=0,                    # no OCS reconfig time modelled
        ocs_tor_link_bw_gbps=100,
        tor_host_link_bw_gbps=100,
        use_webserver=True,
        simulation_stop_s=1.0,
    )
    circuits = OpticalTopo.opera(nb_node=nb_node, nb_link=nb_link)
    assert net.deploy_topo(circuits)
    paths = OpticalRouting.routing_hoho(net.get_topo())
    assert net.deploy_routing(paths, routing_mode="Per-hop")

    net.udp_traffic() \
        .echo(0, 2, start_s=0.05, stop_s=0.8,
              num_packets=20, interval_s=0.03) \
        .install()
    net.start()
