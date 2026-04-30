"""VLB with a randomised first hop.

``routing_vlb(random=True)`` emits a source-routed first-hop sentinel
``(cur_node=255, send_ts=255, send_port_or_node=255)`` meaning "the
ingress ToR picks an egress uplink uniformly at random and sends
immediately in the current slice". The intermediate ToR then uses the
node-type second hop to resolve the route to the final destination via
its ``cal_port_slice_to_node`` table.

Contrast with ``ns3_routing_vlb.py`` where the first hop is deterministic
per slice. Because the random choice is drawn from ns-3's
``UniformRandomVariable``, two runs with the same ns-3 RNG seed produce
the same sequence of uplink choices — the simulation stays fully
deterministic even with "random" VLB.
"""

from openoptics import Toolbox, OpticalTopo, OpticalRouting

if __name__ == "__main__":
    nb_node = 8
    nb_link = 2
    net = Toolbox.BaseNetwork(
        name="ns3_routing_vlb_random",
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
    paths = OpticalRouting.routing_vlb(
        net.get_topo(), net.tor_ocs_ports, random=True,
    )
    assert net.deploy_routing(paths, routing_mode="Source")

    net.udp_traffic() \
        .echo(0, 2, start_s=0.05, stop_s=0.8,
              num_packets=20, interval_s=0.03) \
        .install()
    net.start()
