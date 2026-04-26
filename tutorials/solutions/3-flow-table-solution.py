##########################################################################################
# You will now enable routing in your optical DCN:

# 1. Add flow table entries for nodes 0 and 1 to enable routing between them.
# 2. Test reachability with ping: `h0 ping h1`, check packets' sequence numbers `icmp_seq`, and reason the packet loss.
# 3. To reduce packet loss, you could add flow table entries for nodes 2 and 3.
# 4. Test reachability again with ping: `h0 ping h1`, and check icmp_seq now.
##########################################################################################

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
    # Modify starting from here: 

    # Copy your topology here:
    net.connect(time_slice=0, node1=0, node2=1)
    net.connect(time_slice=0, node1=2, node2=3)

    net.connect(time_slice=1, node1=0, node2=2)
    net.connect(time_slice=1, node1=1, node2=3)

    net.connect(time_slice=2, node1=0, node2=3)
    net.connect(time_slice=2, node1=1, node2=2)

    net.deploy_topo()

    # Add flow table entries here

    node0_entries = [
        TimeFlowEntry(
            dst=1, hops=TimeFlowHop(send_port=0)
        ),
        TimeFlowEntry(
            dst=2, hops=TimeFlowHop(send_port=0)
        ),
        TimeFlowEntry(
            dst=3, hops=TimeFlowHop(send_port=0)
        ),
    ]

    node1_entries = [
        TimeFlowEntry(
            dst=0, hops=TimeFlowHop(send_port=0)
        ),
        TimeFlowEntry(
            dst=2, hops=TimeFlowHop(send_port=0)
        ),
        TimeFlowEntry(
            dst=3, hops=TimeFlowHop(send_port=0)
        ),
    ]

    """

    node2_entries = [
        TimeFlowEntry(
            dst=0, hops=TimeFlowHop(send_port=0)
        ),
        TimeFlowEntry(
            dst=1, hops=TimeFlowHop(send_port=0)
        ),
        TimeFlowEntry(
            dst=3, hops=TimeFlowHop(send_port=0)
        ),
    ]

    node3_entries = [
        TimeFlowEntry(
            dst=0, hops=TimeFlowHop(send_port=0)
        ),
        TimeFlowEntry(
            dst=1, hops=TimeFlowHop(send_port=0)
        ),
        TimeFlowEntry(
            dst=2, hops=TimeFlowHop(send_port=0)
        ),
    ]
    """

    net.setup_nodes()
    net.add_time_flow_entry(node_id=0, entries=node0_entries)
    net.add_time_flow_entry(node_id=1, entries=node1_entries)
    #net.add_time_flow_entry(node_id=2, entries=node2_entries)
    #net.add_time_flow_entry(node_id=3, entries=node3_entries)

    net.start()
