# Installation

OpenOptics ships on PyPI. How you install depends on which backend you plan
to use.

## Path A — Mininet backend (Docker image + `pip install`)

The Mininet backend needs native components that pip cannot usefully provide:
BMv2 binaries, the Mininet `mn` CLI, OVS, kernel network namespace support.
The `ymlei/openoptics:latest` Docker image ships all of that prebuilt. You
add the Python package on top with `pip install`.

```bash
# On a remote machine? Forward the dashboard port first:
ssh -L localhost:8001:localhost:8001 YOUR_MACHINE

sudo docker pull ymlei/openoptics:latest
sudo docker run --privileged -dit --network host \
     --name openoptics ymlei/openoptics:latest /bin/bash
sudo docker exec -it openoptics bash

# Inside the container:
pip install "openoptics-dcn[mininet]"
openoptics-gen-examples          # copies ./examples/
python3 examples/mininet_routing_direct_perhop.py
```

The dashboard (Redis + Django migrations + runserver) starts automatically when your script creates a `BaseNetwork` with `use_webserver=True` (the default).

See [Quick Start](quickstart.rst) for a walkthrough.

## Path B — Tofino backend (plain `pip install`, no Docker)

The Tofino backend's heavy dependencies (Intel SDE, P4 compiler) live on the
switches and are invoked over SSH. Your workstation only needs Python:

```bash
pip install "openoptics-dcn[tofino]"
openoptics-gen-config            # writes ./openoptics-tofino.toml
# edit the placeholders for your testbed, then write a deploy script that
# sets config_file="openoptics-tofino.toml".
```

See [Tofino Backend](tofino-backend.md) for prerequisites and
config details.

## Path C — Core library only (pure Python, any environment)

If you only need the topology generators, routing algorithms, or offline
analysis (no hardware or emulation), install just the core:

```bash
pip install openoptics-dcn
```

This pulls `networkx` and `numpy` and nothing else. Useful for algorithm
development, unit testing with `tests/helpers.FakeBackend`, or running
OpenOptics from a notebook.

## Install extras reference

| Extra | What it pulls | When you need it |
|---|---|---|
| *(none)* | `networkx`, `numpy` | Topology/routing algorithms, offline analysis |
| `[mininet]` | `mininet`, `thrift`, + dashboard deps | Mininet backend (also requires BMv2 + `mn` — use the Docker image) |
| `[tofino]` | `paramiko`, `tomli` (Py<3.11) | Tofino backend (deploys to switches over SSH) |
| `[viz]` | `matplotlib` | `OpticalTopo.plot_graph()` standalone |
| `[all]` | All of the above | Combined install |

## Bundled CLI tools

After `pip install`, these commands are on your `PATH`:

| Command | What it does |
|---|---|
| `openoptics-gen-examples` | Copies bundled `examples/` into current directory |
| `openoptics-gen-tutorials` | Copies bundled `tutorials/` into current directory |
| `openoptics-gen-config` | Writes an editable Tofino config template (`openoptics-tofino.toml`) |

All three accept `-o PATH` and `--force`.

## Advanced: build from source

If you need to modify the custom BMv2 switch targets or the P4 programs, you
can build the development image yourself instead of pulling
`ymlei/openoptics:latest`:

```bash
git clone https://github.com/mpi-ncs/openoptics.git
cd openoptics
sudo docker build -t openoptics-dev:local .
sudo docker run --privileged -dit --network host \
     --name openoptics \
     -v "$PWD:/openoptics" \
     openoptics-dev:local /bin/bash
sudo docker exec -it openoptics bash

# Inside the container, use an editable install so your edits take effect:
cd /openoptics
pip install -e ".[mininet]"
```

The Dockerfile compiles BMv2 (from [p4lang/behavioral-model](https://github.com/p4lang/behavioral-model),
commit pinned) with the `optical_switch` and `tor_switch` custom targets
located in `openoptics/backends/mininet/targets/`. If you change those
targets or the P4 sources in `openoptics/backends/mininet/p4src/`, rebuild
the image.
