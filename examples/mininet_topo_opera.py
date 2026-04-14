from openoptics import Toolbox, OpticalTopo

if __name__ == "__main__":
    nb_node = 8
    nb_link = 4
    net = Toolbox.BaseNetwork(
        name="mininet_topo_opera",
        backend="Mininet",
        nb_node=nb_node,
        nb_link=nb_link,
        time_slice_duration_ms=256,  # in ms
        use_webserver=True,
    )
    circuits = OpticalTopo.opera(nb_node, nb_link)
    # print(circuits)
    assert net.deploy_topo(circuits)
    net.start()
