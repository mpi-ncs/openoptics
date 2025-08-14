##########################################################################################
# In this task, you will route packets through multi-hop paths, instead of
# waiting for the direct connection to be established. Goals are:
# (1) make ping work without packet loss
# (2) route packets via multi-hop path to reduce waiting time.
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

    node0_entries = [
        TimeFlowEntry(
            dst=1, arrival_ts=0, hops=[TimeFlowHop(cur_node=0, send_ts=0, send_port=0)]
        ),
        TimeFlowEntry(
            dst=1,
            arrival_ts=1,
            hops=[
                TimeFlowHop(cur_node=0, send_ts=1, send_port=0),
                TimeFlowHop(cur_node=2, send_ts=2, send_port=0),
            ],
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
            dst=0,
            arrival_ts=1,
            hops=[
                TimeFlowHop(cur_node=1, send_ts=1, send_port=0),
                TimeFlowHop(cur_node=3, send_ts=2, send_port=0),
            ],
        ),
        TimeFlowEntry(
            dst=0, arrival_ts=2, hops=[TimeFlowHop(cur_node=1, send_ts=0, send_port=0)]
        ),
    ]

    net.add_time_flow_entry(node_id=0, entries=node0_entries, routing_mode="Source")
    net.add_time_flow_entry(node_id=1, entries=node1_entries, routing_mode="Source")

    net.start()
