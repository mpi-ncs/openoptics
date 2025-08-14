import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from openoptics import Toolbox, OpticalTopo

if __name__ == "__main__":
    nb_node = 8
    nb_link = 4

    net = Toolbox.BaseNetwork(
        name="opera",
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
