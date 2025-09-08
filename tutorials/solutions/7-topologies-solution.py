##########################################################################################
# Programming with low-level APIs can be tedious and error-prone.
# This example demonstrates how to use OpenOptics' high-level APIs to
# build optical data center networks (DCNs) with just a few lines of code.
#
# In this task, your challenge is to modify the round_robin topology functions
# of use it to build your own topology function to reduce average RTT of a 
# cutomized application.
##########################################################################################

from openoptics import Toolbox, OpticalTopo, OpticalRouting

"""
Circuit:
[time_slice, node1, node2, port1, port2]
"""

def my_topology(nb_node):
    nodes = list(range(nb_node))
    middle = nb_node // 2
    micro_ts = middle - 1

    circuits = []
    circuits += OpticalTopo.round_robin(nodes=nodes[:middle], start_time_slice=0)
    circuits += OpticalTopo.round_robin(nodes=nodes[middle:], start_time_slice=0)
    circuits += OpticalTopo.round_robin(nodes=nodes, start_time_slice=micro_ts)

    return circuits

if __name__ == "__main__":
    nb_node = 8
    nb_link = 1

    net = Toolbox.BaseNetwork(
        name="task7-topology",
        backend="Mininet",
        nb_node=nb_node,
        nb_link=nb_link,
        time_slice_duration_ms=128,  # in ms
        use_webserver=True,
    )

    circuits = my_topology(nb_node)
    assert net.deploy_topo(circuits)

    paths = OpticalRouting.routing_direct(net.get_topo())
    assert net.deploy_routing(paths)

    net.start()
