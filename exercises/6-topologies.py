##########################################################################################
# Programming with low-level APIs can be tedious and error-prone.
# This example demonstrates how to use OpenOptics' high-level APIs to
# build optical data center networks (DCNs) with just a few lines of code.
#
# In this task, your challenge is to modify the round_robin topology to
# generate a schedule with 'n' groups, where the bandwidth within each group
# is 'k' times of the bandwidth between groups.
##########################################################################################


import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from openoptics import Toolbox, OpticalTopo, OpticalRouting


def grounped_round_robin(nb_node, n, k):
    """Generate a schedule with 'n' groups, where the bandwidth within each group
    is 'k' times of the bandwidth between groups across all time slices."""
    pass


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
    assert net.deploy_routing(paths, routing_mode="Source")

    net.start()
