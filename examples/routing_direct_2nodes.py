import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from openoptics import Toolbox, OpticalTopo, OpticalRouting

if __name__ == "__main__":
    net = Toolbox.BaseNetwork(
        name="my_network",
        backend="Mininet",
        nb_node=8,
        time_slice_duration_ms=2,  # in ms
        use_webserver=True,
    )

    circuits = OpticalTopo.round_robin(nb_node=8)
    # print(circuits)
    assert net.deploy_topo(circuits)

    paths = OpticalRouting.find_direct_path(net.slice_to_topo, node1=0, node2=1)
    paths.extend(OpticalRouting.find_direct_path(net.slice_to_topo, node1=1, node2=0))
    # for path in paths:
    # print(str(path))
    net.deploy_routing(paths, routing_mode="Per-hop")

    net.start()
