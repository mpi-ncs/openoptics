# Installation

OpenOptics ships on PyPI. How you install depends on which backend you plan
to use.

## Mininet backend (Docker image + `pip install`)

The Mininet backend needs components (e.g. BMv2 binaries) that pip cannot properly provide.
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

The dashboard (FastAPI + Uvicorn) starts in-process automatically when your script creates a `BaseNetwork` with `use_webserver=True` (the default). No Redis, no separate server — everything runs inside the Python process.

Configure via environment variables (all optional):

| Variable | Default | Purpose |
|---|---|---|
| `OPENOPTICS_STATE_DIR` | `~/.openoptics` | SQLite DB + generated topology images |
| `OPENOPTICS_DASHBOARD_HOST` | `localhost` | Bind host for the web UI |
| `OPENOPTICS_DASHBOARD_PORT` | `8001` | Bind port for the web UI |
| `OPENOPTICS_DASHBOARD_POLL_INTERVAL` | `1.0` | Metric polling interval in seconds |

See [Quick Start](quickstart.rst) for a walkthrough.

## Tofino backend (plain `pip install`, no Docker)

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

## ns-3 backend (plain `pip install` + local ns-3 build)

The ns-3 backend runs packet-level simulations in a regular Python process.
It does not need Docker, Mininet, BMv2, or switch hardware, but it does need a
local ns-3 checkout built with Python bindings.

```bash
# System deps on Debian/Ubuntu:
sudo apt install -y git g++ cmake pkg-config python3-dev \
                    python3-setuptools libgsl-dev libxml2-dev

# OpenOptics and ns-3's Python binding dependency:
pip install "openoptics-dcn[ns3]"
pip install cppyy

# Clone ns-3, link the OpenOptics contrib module, and build it.
# The default target is ~/ns-3-dev and the default ns-3 tag is ns-3.44.
openoptics-install-ns3 ~/ns-3-dev
```

The installer records the ns-3 checkout in
`$OPENOPTICS_STATE_DIR/ns3_env.json` (default `~/.openoptics/ns3_env.json`).
After that, OpenOptics ns-3 scripts can usually run without manual
`NS3_DIR` or `PYTHONPATH` exports:

```bash
openoptics-gen-examples
python3 examples/ns3_routing_direct_perhop.py
```

If you want to import ns-3 directly with `from ns import ns`, or you want to
override the recorded checkout for one shell, evaluate the installer's
environment output:

```bash
eval "$(openoptics-install-ns3 --print-env-only ~/ns-3-dev)"
```

Common installer variants:

```bash
openoptics-install-ns3                      # build into ~/ns-3-dev
openoptics-install-ns3 /opt/ns-3-dev        # choose a target directory
openoptics-install-ns3 --skip-clone PATH    # use an existing ns-3 checkout
openoptics-install-ns3 --skip-build PATH    # link only, do not rebuild
openoptics-install-ns3 --dry-run PATH       # show planned commands
openoptics-install-ns3 --ns3-version ns-3.45 PATH
```

See [ns-3 Backend](ns3-backend.md) for the full backend guide, simulation
parameters, traffic generation examples, and implementation notes.

## Core library only (pure Python, any environment)

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
| `[ns3]` | No extra Python packages | ns-3 backend (also requires `cppyy`, ns-3 build deps, and `openoptics-install-ns3`) |
| `[viz]` | `matplotlib` | `OpticalTopo.plot_graph()` standalone |
| `[all]` | All of the above | Combined install |

## Bundled CLI tools

After `pip install`, these commands are on your `PATH`:

| Command | What it does |
|---|---|
| `openoptics-gen-examples` | Copies bundled `examples/` into current directory |
| `openoptics-gen-tutorials` | Copies bundled `tutorials/` into current directory |
| `openoptics-gen-config` | Writes an editable Tofino config template (`openoptics-tofino.toml`) |
| `openoptics-install-ns3` | Clones/builds ns-3 and links the OpenOptics contrib module |

The `openoptics-gen-*` commands accept `-o PATH` and `--force`.

## Install from GitHub

Use an editable GitHub install when you need unreleased Tofino or ns-3 backend
changes, local examples/docs, or a source tree you can modify.

Start by cloning the repo:

```bash
git clone https://github.com/mpi-ncs/openoptics.git
cd openoptics
```

For the Tofino backend, install the Tofino extra from the checkout:

```bash
pip install -e ".[tofino]"
openoptics-gen-config            # writes ./openoptics-tofino.toml
# edit the placeholders for your testbed, then use
# config_file="openoptics-tofino.toml" in your deploy script.
```

For the ns-3 backend, install the ns-3 extra from the checkout, then build
ns-3 with the OpenOptics contrib module linked in:

```bash
# System deps on Debian/Ubuntu:
sudo apt install -y git g++ cmake pkg-config python3-dev \
                    python3-setuptools libgsl-dev libxml2-dev

pip install -e ".[ns3]"
pip install cppyy
openoptics-install-ns3 ~/ns-3-dev
```

After the ns-3 installer records `~/ns-3-dev`, verify the editable checkout
through an example:

```bash
openoptics-gen-examples
python3 examples/ns3_routing_direct_perhop.py
```

See [Tofino Backend](tofino-backend.md) and [ns-3 Backend](ns3-backend.md)
for backend-specific setup and runtime details.

## Build Mininet backend Docker image manually

This section is for the Mininet backend. If you need to modify the custom BMv2
switch targets or the P4 programs, you can build the development image yourself
instead of pulling `ymlei/openoptics:latest`:

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
