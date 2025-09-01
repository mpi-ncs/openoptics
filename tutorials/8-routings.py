import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import networkx as nx
from typing import Dict

from openoptics import Toolbox, OpticalTopo, OpticalRouting
from openoptics.TimeFlowTable import Path, Step

"""
Circuit:
[time_slice, node1, node2, port1, port2]
"""
def my_topology(nb_node):

    nodes = list(range(nb_node))
    half = nb_node // 2
    circuits = []

    # Internal circuits
    circuits += OpticalTopo.round_robin(nodes=nodes[:half], start_time_slice=0)
    circuits += OpticalTopo.round_robin(nodes=nodes[half:], start_time_slice=0)
    circuits += [
        [half-1, 0, 4, 0, 0],
        [half-1, 1, 5, 0, 0],
        [half-1, 2, 6, 0, 0],
        [half-1, 3, 7, 0, 0]
    ]

    return circuits

def my_routing(slice_to_topo: Dict[int, nx.Graph]):
    """
    This is the implementation of direct routing.
    """
    paths = []

    nodes = slice_to_topo[0].nodes()
    for node1 in nodes:
        for node2 in nodes:
            if node1 == node2:
                continue
            paths.extend(OpticalRouting.find_direct_path(slice_to_topo, node1, node2))

    return paths

if __name__ == "__main__":
    nb_node = 8
    nb_link = 1

    net = Toolbox.BaseNetwork(
        name="task8-routings",
        backend="Mininet",
        nb_node=nb_node,
        nb_link=nb_link,
        time_slice_duration_ms=128,  # in ms
        use_webserver=True,
    )

    circuits = my_topology(nb_node)
    assert net.deploy_topo(circuits)

    #paths = OpticalRouting.routing_direct(net.get_topo())
    paths = my_routing(net.get_topo())
    assert net.deploy_routing(paths, routing_mode="Source")

    net.start()
