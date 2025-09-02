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
    For h0-5 only.
    """
    paths = []

    nodes = slice_to_topo[0].nodes()
    
    # paths for node 0
    paths.extend([
        Path(src=0, arrival_ts=0, dst=5, 
                steps=[
                Step(send_port=0, send_ts=2), # First send to node 1 at time slice 2
                Step(send_port=0, send_ts=3) # Send from node 1 to node 5 at time slice 3
                ]),
        Path(src=0, arrival_ts=1, dst=5, 
                steps=[
                Step(send_port=0, send_ts=2), # First send to node 1 at time slice 2
                Step(send_port=0, send_ts=3) # Send from node 1 to node 5 at time slice 3
                ]),
        Path(src=0, arrival_ts=2, dst=5, 
                steps=[
                Step(send_port=0, send_ts=2), # First send to node 1 at time slice 2
                Step(send_port=0, send_ts=3) # Send from node 1 to node 5 at time slice 3
                ]),
        
        Path(src=0, arrival_ts=3, dst=5, 
                steps=[
                Step(send_port=0, send_ts=3), # First send to node 4 at time slice 3
                Step(send_port=0, send_ts=2) # Send from node 4 to node 5 at time slice 2
                ])
        ])
    
    # paths for node 5
    paths.extend([
        Path(src=5, arrival_ts=0, dst=0, 
                steps=[
                Step(send_port=0, send_ts=2), # First send to node 4 at time slice 2
                Step(send_port=0, send_ts=3) # Send from node 4 to node 0 at time slice 3
                ]),
        Path(src=5, arrival_ts=1, dst=0, 
                steps=[
                Step(send_port=0, send_ts=2), # First send to node 4 at time slice 2
                Step(send_port=0, send_ts=3) # Send from node 4 to node 0 at time slice 3
                ]),
        Path(src=5, arrival_ts=2, dst=0, 
                steps=[
                Step(send_port=0, send_ts=2), # First send to node 4 at time slice 2
                Step(send_port=0, send_ts=3) # Send from node 4 to node 0 at time slice 3
                ]),
        
        Path(src=5, arrival_ts=3, dst=0, 
                steps=[
                Step(send_port=0, send_ts=3), # First send to node 1 at time slice 3
                Step(send_port=0, send_ts=2) # Send from node 1 to node 0 at time slice 2
                ]),
    ])
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
