(1-get-started)=
# Tutorial 1: Get Started

This tutorial guides you through running a pre-written script to deploy a simple optical Data Center Network (DCN) using Mininet.

First, log in to your VM. The `-L` flag forwards the port for the web dashboard, allowing you to access it from your local machine.

```bash
ssh -L8001:0.0.0.0:8001 root@sigcomm-tutorial-X
```

If you are using VS Code with Remote Development, you can also use this command to connect your editor to the VM.

## Running the Example

1. Execute the OpenOptics script.

From the openoptics project root directory inside the container, run the following command:

```bash
    cd openoptics/tutorial
    python3 tutorial/1-get-started.py
```

The script (tutorial/1-get-started.py) contains the following code:

```python
    from openoptics import Toolbox, OpticalTopo, OpticalRouting
        
    if __name__ == "__main__":

        nb_node = 8

        net = Toolbox.BaseNetwork(
            name="task1",
            backend="Mininet",
            nb_node = nb_node,
            time_slice_duration_ms = 512, # in ms
            use_webserver=True)
        
        circuits = OpticalTopo.round_robin(nb_node=nb_node)
        assert net.deploy_topo(circuits)

        paths = OpticalRouting.routing_direct(net.slice_to_topo)
        assert net.deploy_routing(paths)

        net.start()
```

This script creates a network with these components:

* An 8-node optical network. 
* A round-robin optical topology. 
* A direct routing between nodes. 
* A web server for monitoring at http://localhost:8001.

Under the hood, BaseNetwork creates a Mininet network with hosts and switches. For this demonstration, it provisions one host per Top-of-Rack (ToR) switch.

After running the script, you can interact with the network through the command-line interface (CLI) and observe the topology and queue depths on the web dashboard.

2. View the dashboard.

Open your web browser and navigate to http://localhost:8001 to see the network topology and real-time queue depth metrics. You should see something like this:
   .. image:: ../assets/tutorial/1-get-started.png

3. Test network connectivity.
   
For example:
```bash
OpenOptics-> h0 ping h1  # Equivalent to execute "ping h1" at h0
```

4. You shoud also see the queue depth changes in the dashboard.

5. Experiment with time slice duration.
Stop the script (Ctrl+D) and modify the time_slice_duration_ms parameter in tutorial/1-get-started.py.
For example, double it:

Modify slice duration and observe change of ping delay and queue depth.

```python
    ...
    time_slice_duration_ms = 1024
    ...
```

With longer slice duration, your should see the delay and queue depth increase.