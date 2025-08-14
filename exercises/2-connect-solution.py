##########################################################################################
# In this task, you will:
# (1) Use the connect API to create a 4-node topology.
# (2) Design time-sliced topologies such that:
#   • In each time slice, each node connects to one other node (because each node only has one link).
#   • Across all time slices, each node connects every other node once.
# You can check the visulized topology via the dashboard on http://localhost:8001
##########################################################################################

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from openoptics import Toolbox

if __name__ == "__main__":
    net = Toolbox.BaseNetwork(
        name="task2",
        backend="Mininet",
        nb_node=4,
        nb_link=1,
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
