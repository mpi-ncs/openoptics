import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from openoptics import Toolbox, OpticalTopo

if __name__ == "__main__":
    nb_node = 4

    net = Toolbox.BaseNetwork(
        name="my_network",
        backend="Mininet",
        nb_node=nb_node,
        time_slice_duration_ms=256,  # in ms
        use_webserver=True,
    )

    circuits = OpticalTopo.round_robin(nb_node=nb_node)
    # print(circuits)
    assert net.deploy_topo(circuits)

    net.start()
