##########################################################################################
# You will now enable routing in your optical DCN:

# 1. Add flow table entries for nodes 0 and 1 to enable routing between them.
# 2. Test reachability with ping: `h0 ping h1`, check packets' sequence numbers `icmp_seq`, and reason the packet loss.
# 3. To reduce packet loss, you could add flow table entries for nodes 2 and 3.
# 4. Test reachability again with ping: `h0 ping h1`, and check icmp_seq now.
##########################################################################################

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from openoptics import Toolbox
from openoptics.TimeFlowTable import TimeFlowHop, TimeFlowEntry

if __name__ == "__main__":
    net = Toolbox.BaseNetwork(
        name="task3",
        backend="Mininet",
        nb_node=4,
        time_slice_duration_ms=256,  # in ms
        use_webserver=True,
    )
    ##########################################
    # Modification starts from here: 

    # Copy your topology here
    net.connect(node1=0, node2=1, time_slice=0)

    net.deploy_topo() # No need to change this line


    # Add flow table entries here

    node0_entries = [
        # An example:
        # As each node has only one link connected to OCS, always set send_port=0.
        TimeFlowEntry(dst=1, hops=TimeFlowHop(send_port=0)),
    ]
    node1_entries = []
    node2_entries = []
    node3_entries = []

    # Load flow table entries to ToR 0-3
    net.add_time_flow_entry(node_id=0, entries=node0_entries)
    net.add_time_flow_entry(node_id=1, entries=node1_entries)
    net.add_time_flow_entry(node_id=2, entries=node2_entries)
    net.add_time_flow_entry(node_id=3, entries=node3_entries)

    # Modification ends here.
    ##########################################

    net.start()
