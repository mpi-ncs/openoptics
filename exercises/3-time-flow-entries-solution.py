##########################################################################################
# In this task, the goal is making ping work without packet loss. You will:
# (1) Add usual flow table entries for node 0 and node 1, by setting send time slice (send_ts)
#     the same as arrival time slice (arrival_ts)
# (2) Test reachability with ping: `h0 ping h1`
# (3) Update flow table to time flow table -
#     adjust send_ts and arrival_ts according to time sliced topology.
# (4) Test reachability again with ping: `h0 ping h1`
##########################################################################################

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from openoptics import Toolbox
from openoptics.TimeFlowTable import TimeFlowHop, TimeFlowEntry

if __name__ == "__main__":
    net = Toolbox.BaseNetwork(
        name="task2",
        backend="Mininet",
        nb_node=4,
        time_slice_duration_ms=256,  # in ms
        use_webserver=True,
    )

    # Copy your topology here
    net.connect(node1=0, node2=1, time_slice=0)
    net.connect(node1=2, node2=3, time_slice=0)

    net.connect(node1=0, node2=2, time_slice=1)
    net.connect(node1=1, node2=3, time_slice=1)

    net.connect(node1=0, node2=3, time_slice=2)
    net.connect(node1=1, node2=2, time_slice=2)

    net.deploy_topo()

    # Add flow table entries here
    node0_entries = []
    node1_entries = []

    node0_entries = [
        TimeFlowEntry(
            dst=1, arrival_ts=0, hops=[TimeFlowHop(cur_node=0, send_ts=0, send_port=0)]
        ),
        TimeFlowEntry(
            dst=1, arrival_ts=1, hops=[TimeFlowHop(cur_node=0, send_ts=0, send_port=0)]
        ),
        TimeFlowEntry(
            dst=1, arrival_ts=2, hops=[TimeFlowHop(cur_node=0, send_ts=0, send_port=0)]
        ),
    ]

    node1_entries = [
        TimeFlowEntry(
            dst=0, arrival_ts=0, hops=[TimeFlowHop(cur_node=1, send_ts=0, send_port=0)]
        ),
        TimeFlowEntry(
            dst=0, arrival_ts=1, hops=[TimeFlowHop(cur_node=1, send_ts=0, send_port=0)]
        ),
        TimeFlowEntry(
            dst=0, arrival_ts=2, hops=[TimeFlowHop(cur_node=1, send_ts=0, send_port=0)]
        ),
    ]

    net.add_time_flow_entry(node_id=0, entries=node0_entries, routing_mode="Source")
    net.add_time_flow_entry(node_id=1, entries=node1_entries, routing_mode="Source")

    net.start()
