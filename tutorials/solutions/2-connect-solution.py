##########################################################################################
# In this task, you will:
# (1) Use the connect API to create a 4-node topology,
# (2) such that:
#   • In each time slice, each node connects to one other node (because each node only has one link).
#   • Across all time slices, each node connects every other node once.
# You can check the visualized topology via the dashboard on http://localhost:8001
##########################################################################################

from openoptics import Toolbox

if __name__ == "__main__":
    net = Toolbox.BaseNetwork(
        name="task2",
        backend="Mininet",
        nb_node=4,
        nb_link=1,
        time_slice_duration_ms=256,  # in ms
        use_webserver=True,
    )

    ##########################################
    # Modification starts from here: 

    # Create your topology schedule with net.connect()
    # Nodes are indexed as 0, 1, 2, 3
    net.connect(time_slice=0, node1=0, node2=1)
    net.connect(time_slice=0, node1=2, node2=3)

    net.connect(time_slice=1, node1=0, node2=2)
    net.connect(time_slice=1, node1=1, node2=3)

    net.connect(time_slice=2, node1=0, node2=3)
    net.connect(time_slice=2, node1=1, node2=2)
    # Modification ends here.
    ##########################################

    net.deploy_topo()

    net.start()
