import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from openoptics import Toolbox

if __name__ == "__main__":
    root = ""
    net = Toolbox.BaseNetwork(
        name="my_network",
        backend="Mininet",
        nb_node=4,
        time_slice_duration_ms=256,  # in ms
        use_webserver=True,
    )

    net.connect(node1=0, node2=1, time_slice=0)
    net.connect(node1=2, node2=3, time_slice=0)

    net.connect(node1=0, node2=2, time_slice=1)
    net.connect(node1=1, node2=3, time_slice=1)

    net.connect(node1=0, node2=3, time_slice=2)
    net.connect(node1=1, node2=2, time_slice=2)

    net.deploy_topo()

    net.start()
