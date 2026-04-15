from openoptics import Toolbox, OpticalTopo

if __name__ == "__main__":
    nb_node = 4
    net = Toolbox.BaseNetwork(
        name="mininet_topo_round_robin",
        backend="Mininet",
        nb_node=nb_node,
        time_slice_duration_ms=256,  # in ms
        use_webserver=True,
    )
    circuits = OpticalTopo.round_robin(nb_node=nb_node)
    # print(circuits)
    assert net.deploy_topo(circuits)
    net.start()
