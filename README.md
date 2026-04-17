<div align="center">
<img alt="OpenOptics" src="https://raw.githubusercontent.com/mpi-ncs/openoptics/main/assets/openoptics_words.svg" width=20%>
<h3>
Easy design, testing, and deployment of optical datacenter networks for everyone
</h3>

<p>
| <a href="https://openoptics.mpi-inf.mpg.de/"><b>Documentation</b></a> | <a href="https://arxiv.org/abs/2411.18319"><b>Paper</b></a> |
</p>

</div>


---

*Latest News* 🔥

- [2026/03] [OpenOptics](https://ymlei.github.io/assets/OpenOptics_CR.pdf) has been accepted by NSDI'26!

---

# What is OpenOptics?

OpenOptics is a general framework for realizing different optical data center network architectures in a plug-and-play manner.
With OpenOptics, users can deploy customized optical data center networks on the testbed, emulation, or simulation with ~10 lines of python code.
Under the hood, user configurations are converted to control plane programs and deployed to the underlining OCSes and P4 switches.

Supported backends:
- **Mininet** — full software emulation using BMv2 software switches and Mininet networks.
- **Tofino** — deployment on Intel Tofino2 programmable switches (SDE 9.12.0). See [docs/tofino-backend.md](docs/tofino-backend.md).
- **ns-3** — packet-level simulation (scaffold; under active development).

# Quick Start

OpenOptics has two installation paths — pick the one that matches the backend
you need.

## For the Mininet backend: Docker image + `pip install`

The `ymlei/openoptics:latest` image ships a fully built BMv2, Mininet, Redis,
and all native dependencies. Add the Python package on top with pip.

```bash
# If you're on a remote machine, forward the dashboard port first:
ssh -L localhost:8001:localhost:8001 YOUR_MACHINE

# Pull and enter the container:
sudo docker pull ymlei/openoptics:latest
sudo docker run --privileged -dit --network host --name openoptics \
     ymlei/openoptics:latest /bin/bash
sudo docker exec -it openoptics bash

# Inside the container:
pip install "openoptics-dcn[mininet]"
openoptics-gen-examples          # copies ./examples/ into cwd
python3 examples/mininet_routing_direct_perhop.py
```

The dashboard (Redis + Django migrations + runserver) starts automatically when your script creates a `BaseNetwork` with `use_webserver=True` (the default).

Then try `h0 ping h1` / `h2 ping h3` inside the OpenOptics CLI.

VS Code Dev Containers also works — Ctrl+Shift+P → "Dev Containers: Reopen in
Container" after `git clone`ing this repo (`.devcontainer/` wires up the same
image).

If you'd rather build the image yourself or install editable from source,
see the [build-from-source section in `docs/installation.md`](docs/installation.md#advanced-build-from-source).

## For the Tofino backend: `pip install` (no Docker)

The Tofino backend only needs Python on your workstation — the heavy
dependencies (Intel SDE, P4 compiler) live on the switches and are invoked
over SSH.

```bash
pip install "openoptics-dcn[tofino]"
openoptics-gen-config            # writes ./openoptics-tofino.toml
# edit the placeholders (USER, jumphost.example.com, IPs, MACs), then run
# a Tofino example — see docs/tofino-backend.md for a full walkthrough.
```

See [docs/tofino-backend.md](docs/tofino-backend.md) for prerequisites and
config details.

## Bundled resources (all installs)

After `pip install`, these commands seed your working directory:

```bash
openoptics-gen-examples          # examples/
openoptics-gen-tutorials         # tutorials/
openoptics-gen-config            # openoptics-tofino.toml (Tofino config template)
```

# Usage

## With Example Scripts

```
python3 examples/mininet_routing_direct_perhop.py
```
Then you can try ping in your optical DCN,
```
h0 ping h1
h2 ping h3
```

## Defining Your Own Optical DCN with Python APIs

![OpenOptics Diagram](https://raw.githubusercontent.com/mpi-ncs/openoptics/main/assets/openoptics-diagram.png)

OpenOptics User APIs are located in `openoptics/Toolbox.py`.
This file defines a number of useful functions for creating optical topologies, deploying routing, and monitoring the network.
Every OpenOptics network is a `BaseNetwork` object:

```python
net = Toolbox.BaseNetwork(
    name="my_network",
    backend="Mininet",
    nb_node = 4,
    time_slice_duration_ms = 32, # in ms
    use_webserver=True)
```

You can use `connect(node1,port1,node2,port2,time_slice)` to connect ports of two nodes at the given time slice.
```python
net.connect(node1=0,port1=0,node2=1,port2=0,time_slice=0)
net.connect(node1=2,port1=0,node2=3,port2=0,time_slice=0)
net.connect(node1=0,port1=0,node2=2,port2=0,time_slice=1)
net.connect(node1=1,port1=0,node2=3,port2=0,time_slice=1)
net.deploy_topo()
```

Or you can use provided high-level topology generators:
```python
circuits = OpticalTopo.round_robin(nb_node=8)
net.deploy_topo(circuits)
```
or
```python
circuits = OpticalTopo.opera(nb_node = 8, nb_link=2)
net.deploy_topo(circuits)
```

Next, you can define routing by adding time-flow table entries (as forwarding tables in electrical DCNs) `add_time_flow_entry(node_id, entries, routing_mode)`.
Or use provided high-level routing generators:
```python
paths = OpticalRouting.routing_direct(net.get_topo())
net.deploy_routing(paths, routing_mode="Per-hop")
```

Once you have created a `BaseNetwork` object, and defined its topology and routing, start the network by simply calling `net.start()`.
Now run your Python file and your first optical DCN is deployed!

`net.start()` launches a command line interface defined in `src/OpticalCLI.py`.
This CLI is an extension of Mininet's CLI, with added support for optical DCNs, e.g. to query the number of queued packets in switches and the network's packet loss rate. 

You can find example scripts configuring different architectures under [examples/](examples/) — or, after `pip install`, run `openoptics-gen-examples` to copy them into your current directory.

## Monitor with OpenOptics Dashboard

![OpenOptics Dashboard](https://raw.githubusercontent.com/mpi-ncs/openoptics/main/assets/dashboard.png)

The dashboard starts automatically when you create a `BaseNetwork` with `use_webserver=True` (the default) — Redis is launched and Django migrations are applied in-process, so no separate setup step is needed.
In your web browser, visit http://0.0.0.0:8001 to view the dashboard.
The dashboard displays the network topology, along with realtime graphs of network performance served via WebSockets. 

Note: If you're running OpenOptics at a remote machine, make sure to enable port forwarding by passing `-L8001:0.0.0.0:8001` to ssh.

## Citation

If you use OpenOptics for your research, please cite our [paper](https://arxiv.org/abs/2411.18319):
```bibtex
@misc{lei2025openopticsopenresearchframework,
      title={OpenOptics: An Open Research Framework for Optical Data Center Networks}, 
      author={Yiming Lei and Federico De Marchi and Jialong Li and Raj Joshi and Balakrishnan Chandrasekaran and Yiting Xia},
      year={2025},
      eprint={2411.18319},
      archivePrefix={arXiv},
      primaryClass={cs.NI},
      url={https://arxiv.org/abs/2411.18319}, 
}
```

## Contact Us

<!-- --8<-- [start:contact-us] -->
- For technical questions and feature requests, please open a GitHub [Issues](https://github.com/mpi-ncs/openoptics/issues)
- For discussions and collaboration, contact us at [ylei@mpi-inf.mpg.de](mailto:ylei@mpi-inf.mpg.de)
<!-- --8<-- [end:contact-us] -->