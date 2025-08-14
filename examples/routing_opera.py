import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from openoptics import Toolbox, OpticalTopo, OpticalRouting

if __name__ == "__main__":
    node_nb = 8
    nb_link = 4

    net = Toolbox.BaseNetwork(
        name="my_network",
        backend="Mininet",
        nb_node=node_nb,
        nb_link=nb_link,
        time_slice_duration_ms=64,  # in ms
        use_webserver=True,
    )

    circuits = OpticalTopo.opera(nb_node=node_nb, nb_link=nb_link)
    assert net.deploy_topo(circuits)

    paths = OpticalRouting.routing_ksp(net.slice_to_topo)
    net.deploy_routing(paths, routing_mode="Source")

    net.start()
