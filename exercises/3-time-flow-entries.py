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

if __name__ == "__main__":
    net = Toolbox.BaseNetwork(
        name="task2",
        backend="Mininet",
        nb_node=4,
        time_slice_duration_ms=256,  # in ms
        use_webserver=True,
    )

    # Copy your topology here
    net.connect(time_slice=0, node1=0, node2=1)
    net.deploy_topo()

    # Add flow table entries here
    node0_entries = [
        # TimeFlowEntry(dst=, arrival_ts=, hops=[TimeFlowHop(cur_node=, send_ts=, send_port=)])
        # cur_node is where the packet at currently. e.g. Set it to src node id for the first hop.
    ]
    node1_entries = []

    net.add_time_flow_entry(node_id=0, entries=node0_entries, routing_mode="Source")
    net.add_time_flow_entry(node_id=1, entries=node1_entries, routing_mode="Source")

    net.start()
