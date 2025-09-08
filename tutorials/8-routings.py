##########################################################################################
# In this tutorial, you are given a topology that does NOT provide 
# direct connections between every pair of nodes. Your goal is to 
# design a routing on this topology to deliver all packets.
#
# Detailed instructions: https://openoptics.mpi-inf.mpg.de/tutorials/8-routing.html
##########################################################################################

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
    This is the implementation of your routing.
    """
    nodes = slice_to_topo[0].nodes()
    paths = []
    # path: Path(src, arrival_ts, dst, steps=[Step(send_port, send_ts)])

    ##########################################
    # Modification starts from here: 

    for node1 in nodes:
        for node2 in nodes:
            if node1 == node2:
                continue
            paths.extend(OpticalRouting.find_direct_path(slice_to_topo, node1, node2))
            """
            # If you prefer to add paths manually
            paths.append(
                Path(src=0, arrival_ts=0, dst=5, 
                        steps=[
                        Step(cur_node=0, send_port=0, send_ts=3), # First send to node 4 at time slice 3
                        Step(cur_node=4, send_port=0, send_ts=1) # Send from node 4 to node 5 at time slice 2
                        ])
                    )
            # cur_node is for source routing to check whether the node the packet arrives is as expected,
            # the apcket will be dropped if cur_node doesn't match the actual arrival node.
            """
    print(paths)
    # Modification ends here.
    ##########################################

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

    # No modifications needed here. 
    # You are supposed to modify the implementation of my_routing function.
    paths = my_routing(net.get_topo())
    assert net.deploy_routing(paths, routing_mode="Source")

    net.start()
