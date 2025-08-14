##########################################################################################
# So far, you have only used source routing, where the entire path is embedded
# in the time flow table and included in the packet.
#
# In this task, you will implement multi-hop routing in per-hop path mode.
# In this mode, packets do not carry the full path. Instead, each node (ToR)
# uses its own per-hop time flow table to determine how to forward packets.
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
    net.connect(node1=0, node2=1, time_slice=0)
    net.deploy_topo()

    # Create Entries for per-hop routing here
    node0_entries = []

    node1_entries = []

    net.add_time_flow_entry(node_id=0, entries=node0_entries, routing_mode="Per-hop")
    net.add_time_flow_entry(node_id=1, entries=node1_entries, routing_mode="Per-hop")

    net.start()
