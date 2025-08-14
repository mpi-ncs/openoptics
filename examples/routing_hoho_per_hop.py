import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from openoptics import Toolbox, OpticalTopo, OpticalRouting

if __name__ == "__main__":
    nb_node = 4
    nb_link = 1

    net = Toolbox.BaseNetwork(
        name="my_network",
        backend="Mininet",
        nb_node=nb_node,
        time_slice_duration_ms=128,  # in ms
        use_webserver=True,
    )

    circuits = OpticalTopo.opera(nb_node=nb_node, nb_link=nb_link)
    assert net.deploy_topo(circuits)

    paths = OpticalRouting.routing_hoho(net.slice_to_topo, max_hop=2)
    assert net.deploy_routing(paths, routing_mode="Per-hop")

    net.start()
