import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from openoptics import Toolbox

if __name__ == "__main__":
    root = ""
    net = Toolbox.BaseNetwork(
        name="my_network", backend="Mininet", nb_node=2, nb_link=4, use_webserver=True
    )

    assert net.connect(0, 0, 1, 0, 0) == True
    assert net.connect(0, 0, 1, 1, 1) == True
    assert net.connect(0, 0, 1, 0, 2) == False
    assert net.connect(0, 0, 1, 2, 3) == True

    # net.start(mode="Mininet")
