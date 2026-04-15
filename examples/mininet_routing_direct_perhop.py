from openoptics import Toolbox, OpticalTopo, OpticalRouting

if __name__ == "__main__":
    nb_node = 4
    net = Toolbox.BaseNetwork(
        name="mininet_routing_direct_perhop",
        backend="Mininet",
        nb_node=nb_node,
        time_slice_duration_ms=1024,  # in ms
        use_webserver=True,
    )
    circuits = OpticalTopo.round_robin(nb_node=nb_node)
    # print(circuits)
    assert net.deploy_topo(circuits)
    paths = OpticalRouting.routing_direct(net.get_topo())
    net.deploy_routing(paths, routing_mode="Per-hop")
    net.start()
