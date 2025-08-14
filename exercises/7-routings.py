##########################################################################################
# Play with routing APIs, check dashboard, and ping delay
##########################################################################################

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from openoptics import Toolbox, OpticalTopo, OpticalRouting

if __name__ == "__main__":
    nb_node = 8
    nb_link = 1

    net = Toolbox.BaseNetwork(
        name="task6",
        backend="Mininet",
        nb_node=nb_node,
        nb_link=nb_link,
        time_slice_duration_ms=256,  # in ms
        use_webserver=True,
    )

    circuits = OpticalTopo.round_robin(nb_node=nb_node)
    # circuits = OpticalTopo.opera(nb_node, nb_link)
    assert net.deploy_topo(circuits)

    paths = OpticalRouting.routing_direct(net.slice_to_topo)
    # paths = OpticalRouting.routing_hoho(net.slice_to_topo, max_hop=2)
    # paths = OpticalRouting.routing_ksp(net.slice_to_topo)

    assert net.deploy_routing(paths, routing_mode="Source")

    net.start()
