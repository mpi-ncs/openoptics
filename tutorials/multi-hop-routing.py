##########################################################################################
# In this task, you will route packets through multi-hop paths, instead of
# waiting for the direct connection to be established. Goals are:
# (1) make ping work without packet loss
# (2) route packets via multi-hop paths to reduce waiting time.
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
    ]
    node1_entries = []

    net.add_time_flow_entry(node_id=0, entries=node0_entries, routing_mode="Source")
    net.add_time_flow_entry(node_id=1, entries=node1_entries, routing_mode="Source")
    net.start()
