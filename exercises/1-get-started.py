##########################################################################################
# In this task, you will
# (1) Run a pre-defined script to deploy a simple optical DCN.
# (2) Open dashboard on http://localhost:8001 to check topology and real time queue depth.
# (3) Test the network with ping to check reachability and delay.
#     e.g. `h0 ping h1` # Equvilent to execute "ping h1" at h0
# (4) Modify slice duration and observe change of ping delay and queue depth.
##########################################################################################


import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from openoptics import Toolbox, OpticalTopo, OpticalRouting

if __name__ == "__main__":
    nb_node = 8

    net = Toolbox.BaseNetwork(
        name="task1",
        backend="Mininet",
        nb_node=nb_node,
        time_slice_duration_ms=512,  # in ms
        use_webserver=True,
    )

    circuits = OpticalTopo.round_robin(nb_node=nb_node)
    assert net.deploy_topo(circuits)

    paths = OpticalRouting.routing_direct(net.slice_to_topo)
    assert net.deploy_routing(paths)

    net.start()
