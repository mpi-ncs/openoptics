# Tutorial 1: Get Started

Welcome to OpenOptics Tutorial!
This first tutorial will help you get familiar with the basic workflow and dashboard.
You’ll run a Python script to deploy a simple optical data center network (DCN) in an emulation environment (Mininet).

Follow the [Quick Start](../quickstart) to install OpenOptics if you haven't.

---

## Step 1: Get the bundled tutorials

After `pip install "openoptics-dcn[mininet]"`, copy the bundled tutorials into
your current working directory and `cd` in:

```bash
openoptics-gen-tutorials          # writes ./tutorials/
cd tutorials
```

If you're on a remote machine and want to view the dashboard in a browser
on your laptop, set up SSH port forwarding once:

```bash
ssh -L localhost:8001:localhost:8001 USER_NAME@YOUR_HOST_NAME
```

You are all set! Let's get started!

### 1. Execute the OpenOptics Python Script.

```bash
python3 1-get-started.py
```

The script (`tutorials/1-get-started.py`) contains:

```python
from openoptics import Toolbox, OpticalTopo, OpticalRouting
    
if __name__ == "__main__":

    nb_node = 8

    net = Toolbox.BaseNetwork(
        name="task1",
        backend="Mininet",
        nb_node = nb_node,
        nb_host_per_tor = 1,
        time_slice_duration_ms = 512, # in ms
        use_webserver=True)
    
    circuits = OpticalTopo.round_robin(nb_node=nb_node)
    assert net.deploy_topo(circuits)

    paths = OpticalRouting.routing_direct(net.get_topo())
    assert net.deploy_routing(paths)

    net.start()
```

This script creates an optical DCN with:

* An 8-node optical network. 
* A round-robin optical topology. 
* A direct routing between nodes. 
* A web server for monitoring at http://localhost:8001.

![Architecture](../../assets/arch.png)


Under the hood, `BaseNetwork` creates a Mininet network with OCS, switches, and hosts (`h0`-`h7`).

Each ToR switch is connected to a port of optical circuit switch (OCS),
and each ToR switch is connected to a host, as we set `nb_host_per_tor = 1`.

### 2. View the dashboard.

After running the script, open your browser and navigate to http://localhost:8001.
You should see the network topology and real-time network metrics.

![Dashboard Example](../../assets/dashboard.png)

### 3. Test Network Connectivity

Use `ping` to test connectivity and delay between hosts:

For example:
```bash
# The first host is named with h0
OpenOptics-> h0 ping h1  # Equivalent to execute "ping h1" at h0
```

You should also see queue depth changes on the dashboard during the `ping` test.

### 4. Experiment with Time Slice Duration

Stop the script (Ctrl+D), then modify the `time_slice_duration_ms` parameter.

For example, change it from **512 -> 1024**
```python
...
time_slice_duration_ms = 1024
...
```

Then rerun the script and observe the change in `ping` delay at CLI and queue depth on the dashboard.
With a longer slice duration, you should see both **delay** and **queue depth** increase.