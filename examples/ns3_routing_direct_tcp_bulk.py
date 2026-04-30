"""ns-3 direct per-hop routing with TCP BulkSend traffic.

Runs a 4-ToR round-robin topology and sends one exact-size TCP transfer from
h0 to h1. Requires `openoptics-install-ns3` and exported NS3_DIR/PYTHONPATH.
Dashboard snapshots run at sub-slice cadence. The TCP app starts inside the
h0->h1 direct slice so the SYN can pass, then a 1 Gbps host link keeps the
single flow feeding packets as the schedule turns to waiting slices, making
the calendar-queue buildup visible before the next direct slice drains it.
"""

from openoptics import Toolbox, OpticalTopo, OpticalRouting


if __name__ == "__main__":
    nb_node = 4
    net = Toolbox.BaseNetwork(
        name="ns3_routing_direct_tcp_bulk",
        backend="ns3",
        nb_node=nb_node,
        time_slice_duration_us=10_000,
        snapshot_interval_us=1_000,
        guardband_ms=0,
        ocs_tor_link_bw_gbps=100,
        tor_host_link_bw_gbps=1,
        use_webserver=True,
        simulation_stop_s=1.0,
    )
    circuits = OpticalTopo.round_robin(nb_node=nb_node)
    assert net.deploy_topo(circuits)
    paths = OpticalRouting.routing_direct(net.get_topo())
    net.deploy_routing(paths, routing_mode="Per-hop")

    net.tcp_traffic() \
        .bulk(0, 1, size_bytes=2_000_000, chunk_size_bytes=1448,
              start_s=0.052, stop_s=0.8) \
        .install()
    net.start()
