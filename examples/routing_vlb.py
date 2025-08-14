import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from openoptics import Toolbox, OpticalTopo, OpticalRouting

if __name__ == "__main__":
    nb_node = 8

    net = Toolbox.BaseNetwork(
        name="VLB",
        backend="Mininet",
        nb_node=nb_node,
        time_slice_duration_ms=64,  # in ms
        use_webserver=False,
    )

    circuits = OpticalTopo.round_robin(nb_node=nb_node)
    assert net.deploy_topo(circuits)

    paths = OpticalRouting.routing_vlb(net.slice_to_topo, net.tor_ocs_ports)
    # for path in paths:
    #    print(path)
    assert net.deploy_routing(paths, routing_mode="Source")

    net.start()
