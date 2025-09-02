import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import networkx as nx
from typing import Dict

from openoptics import Toolbox, OpticalTopo, OpticalRouting
from openoptics.TimeFlowTable import Path, Step

def my_topology(nb_node):
    # Do NOT change this function

    nodes = list(range(nb_node))
    half = nb_node // 2
    circuits = []
    """
    A circuit: [time_slice, node1, node2, port1, port2]
    """

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
    This is the implementation of multi-hop routing.
    """
    paths = []

    nodes = slice_to_topo[0].nodes()
    for node1 in nodes:
        for node2 in nodes:
            if node1 == node2:
                continue
            if (node1 // 4 == node2 // 4) or (node1 % 4 == node2 % 4):
                # Nodes within the same cluster, wait for the direct path.
                #print(f"Find direct path for {node1} and {node2}")
                paths.extend(OpticalRouting.find_direct_path(slice_to_topo, node1, node2))
            else:
                # Nodes are in different clusters and they don't have direct connections.
                intermidiate_node = int((node1 + len(nodes)/2) % len(nodes))
                # for 0 -> 5, intermidiate node = (0+4)%8 = 4
                # for 2 -> 5, intermidiate node = (2+4)%8 = 6
                # for 5 -> 2, intermidiate node = (5+4)%8 = 1
                
                paths_to_the_other_gorup = OpticalRouting.find_direct_path(slice_to_topo, node1, intermidiate_node)
                paths_to_dst = OpticalRouting.find_direct_path(slice_to_topo, intermidiate_node, node2)

                for path in paths_to_the_other_gorup:
                    path.dst = node2
                    for sec_hop in paths_to_dst:
                        if sec_hop.arrival_ts == sec_hop.steps[0].send_ts:
                            # this is the step we need
                            path.steps.append(sec_hop.steps[0])
                            paths.append(path)
                            
    #print(f"Paths: {paths}")
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

    paths = my_routing(net.get_topo())
    assert net.deploy_routing(paths, routing_mode="Source")

    net.start()
