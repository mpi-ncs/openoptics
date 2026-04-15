from openoptics import Toolbox, OpticalTopo, OpticalRouting

if __name__ == "__main__":
    nb_node = 8
    net = Toolbox.BaseNetwork(
        name="mininet_routing_direct_source",
        backend="Mininet",
        nb_node=8,
        time_slice_duration_ms=256,  # in ms
        use_webserver=True,
    )
    circuits = OpticalTopo.round_robin(nb_node=8)
    # print(circuits)
    assert net.deploy_topo(circuits)
    paths = OpticalRouting.routing_direct(net.get_topo())
    net.deploy_routing(paths, routing_mode="Source")
    net.start()
