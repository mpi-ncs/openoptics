from openoptics import Toolbox, OpticalTopo, OpticalRouting

if __name__ == "__main__":
    net = Toolbox.BaseNetwork(
        name="mininet_routing_direct_next_node_source",
        backend="Mininet",
        nb_node=8,
        time_slice_duration_ms=2,  # in ms
        use_webserver=False,
    )
    circuits = OpticalTopo.round_robin(nb_node=8)
    # print(circuits)
    assert net.deploy_topo(circuits)
    paths = OpticalRouting.routing_direct_next_node(net.get_topo())
    net.deploy_routing(paths, routing_mode="Source")
    net.start()
