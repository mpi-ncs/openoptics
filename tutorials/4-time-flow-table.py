##########################################################################################
# In this task, the goal is making ping work without packet loss. You will:
# (1) Add usual flow table entries for node 0 and node 1, by setting send time slice (send_ts)
#     the same as arrival time slice (arrival_ts)
# (2) Test reachability with ping: `h0 ping h1`
# (3) Update flow table to time flow table -
#     adjust send_ts and arrival_ts according to time sliced topology.
# (4) Test reachability again with ping: `h0 ping h1`
#
# Detailed instructions: https://openoptics.mpi-inf.mpg.de/tutorials/4-time-flow-table.html
##########################################################################################

from openoptics import Toolbox
from openoptics.TimeFlowTable import TimeFlowHop, TimeFlowEntry

if __name__ == "__main__":
    net = Toolbox.BaseNetwork(
        name="task4",
        backend="Mininet",
        nb_node=4,
        time_slice_duration_ms=256,  # in ms
        use_webserver=True,
    )

    ##########################################
    # Modification starts from here: 


    # Copy your topology here
    net.connect(time_slice=0, node1=0, node2=1)
    net.deploy_topo()

    # Add flow table entries here
    node0_entries = [
        # An example:
        # As each node has only one link connected to OCS, always set send_port=0.
        TimeFlowEntry(
            dst=1, arrival_ts=0,
            hops=TimeFlowHop(send_port=0, send_ts=0)
            ),
    ]
    node1_entries = []

    net.setup_nodes()
    net.add_time_flow_entry(node_id=0, entries=node0_entries)
    net.add_time_flow_entry(node_id=1, entries=node1_entries)

    # Modification ends here.
    ##########################################
    
    net.start()
