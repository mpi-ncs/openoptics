##########################################################################################
# Programming with low-level APIs can be tedious and error-prone.
# The following two tutorials demonstrate how to use OpenOptics' high-level APIs to
# build optical data center networks (DCNs) with just a few lines of code.
#
# In this task, your challenge is to use the round_robin topology functions
# to build your own topology function for a cutomized application.
#
# Detailed instructions: https://openoptics.mpi-inf.mpg.de/tutorials/7-topology.html
##########################################################################################

from openoptics import Toolbox, OpticalTopo, OpticalRouting


def my_topology(nb_node):

    nodes = list(range(nb_node))
    circuits = []
    """
    A circuit: [time_slice, node1, node2, port1, port2]
    As each ToR has only one link, port1/port2 should be 0 (the first port).
    """
    ##########################################
    # Modification starts from here: 
    
    circuits += OpticalTopo.round_robin(
        nodes=nodes, # The nodes group to have round-robin topology
        start_time_slice=0 # The starting time slice of the round-robin topology
        )

    # Modification ends here.
    ##########################################

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

    # No modifications needed here. 
    # You are supposed to modify the implementation of my_topology function.

    circuits = my_topology(nb_node=nb_node)
    assert net.deploy_topo(circuits)

    paths = OpticalRouting.routing_direct(net.get_topo())
    assert net.deploy_routing(paths)

    net.start()
