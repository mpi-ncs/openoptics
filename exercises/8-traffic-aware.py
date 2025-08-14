import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from openoptics import Toolbox, OpticalTopo, OpticalRouting

import threading

stop_event = threading.Event()

if __name__ == "__main__":
    nb_node = 4
    nb_link = 1

    net = Toolbox.BaseNetwork(
        name="my_network",
        backend="Mininet",
        nb_node=nb_node,
        nb_link=nb_link,
        time_slice_duration_ms=128,  # in ms
        arch_mode="TA",
        use_webserver=True,
    )

    circuits = OpticalTopo.static_topo(nb_node=nb_node, nb_link=nb_link)
    assert net.deploy_topo(circuits)

    paths = OpticalRouting.routing_direct_ta(net.slice_to_topo)

    net.deploy_routing(paths, routing_mode="Per-hop", arch_mode="TA", start_fresh=True)

    net.start_traffic_aware(
        OpticalTopo.bipartite_matching,
        OpticalRouting.routing_direct_ta,
        routing_mode="Per-hop",
        updater_interval=1,
    )
