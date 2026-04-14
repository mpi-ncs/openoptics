# Tofino Hardware Backend

OpenOptics supports deployment on programmable switches (Tofino). The Tofino
backend exposes the same Python API as the Mininet backend — the optical-DCN
configuration script is unchanged — but packets flow through real hardware
instead of a software emulation.

This document covers:

1. [What is supported today](#1-status)
2. [User guide](#2-user-guide) — how to configure and run
3. [System workflow](#3-system-workflow) — what happens under the hood

---

## 1. Status

**Hardware target.** Tofino2, SDE 9.12.0. Each physical Tofino2 hosts up to four
logical ToRs, one per pipe. The OCS is emulated on a separate Tofino2.

**What works end-to-end on hardware:**

| Area | Status |
|---|---|
| Deployment pipeline (SSH → SCP → `p4_build.sh` → `bf_switchd` → `bfshell`) | ✅ |
| Jump-host SSH tunneling with paramiko | ✅ |
| Parallel multi-ToR deployment | ✅ |
| OCS emulation | ✅ |
| ToR data plane: `time_flow_table`, calendar queues, AFC pause/resume, per-port queue-depth estimation | ✅ |
| Admission-controlled reroute | ✅ |
| Per-hop and source routing (≤ 2 hops) | ✅ |
| Routing algorithms: Direct, VLB, HoHo, Opera | ✅ |
| Built-in CLI: `server_check`, `server_ping`, `h0 ping h1` | ✅ |

Examples in [`examples/`](../examples/): `tofino_4node_1link_direct.py`,
`tofino_4node_1link_hoho.py`, `tofino_4node_1link_hoho_source.py`,
`tofino_4node_1link_vlb_source.py`, `tofino_4node_2link_direct.py`,
`tofino_4node_2link_hoho.py`, `tofino_4node_2link_vlb_source.py`.

---

## 2. User guide

### 2.1 Prerequisites

| Requirement | Details |
|---|---|
| Tofino2 switches | One OCS switch + one or more ToR switches |
| Intel SDE | `bf-sde-9.12.0` installed at the path set in `[sde]` |
| SSH access | Key-based SSH from the dev container to all switches (directly or via a jump host). Jump host needs a key on disk that can reach the switches. |

### 2.2 Quick start

Before the first run, render a private config with your testbed's real
hostnames, IPs, and MACs (see [§2.3](#23-config-file) for details):

```bash
cd openoptics/backends/tofino
cp secrets.local.toml.example secrets.local.toml
# edit secrets.local.toml with your values
python3 apply_secrets.py    # writes config_*.local.toml
```

Then use the generated `.local.toml` as the `config_file`:

```python
from openoptics import Toolbox, OpticalTopo, OpticalRouting
import os

config_file = os.path.join(
    os.path.dirname(__file__),
    "..", "openoptics", "backends", "tofino", "config_4tor_2link.local.toml",
)

net = Toolbox.BaseNetwork(
    name="tofino_4node_2link_direct",
    backend="Tofino",           # only change from Mininet
    nb_node=4,
    nb_link=2,
    time_slice_duration_us=50,
    config_file=config_file,
)

circuits = OpticalTopo.opera(nb_node=4, nb_link=2, guardband=True)
net.deploy_topo(circuits)

paths = OpticalRouting.routing_direct(net.get_topo())
net.deploy_routing(paths, routing_mode="Per-hop")

net.start()   # opens the OpenOptics CLI
```

Run from inside the dev container:

```bash
sudo docker exec -w /openoptics/examples openoptics bash -c \
  "python3 tofino_4node_2link_direct.py"
```

In the CLI:

```
server_check           # bring up NICs, set IPs, install ARP on both servers
server_ping 0 1        # ping from server on ToR 0 to server on ToR 1
h0 ping h1             # same, via hN shorthand
```

Press `Ctrl-D` to exit; `net.stop()` runs automatically and kills the remote
processes (`pkill -9`).

### 2.3 Config file

The backend reads a TOML config passed via `config_file=`. Two committed
templates in [`openoptics/backends/tofino/`](../openoptics/backends/tofino/)
cover the common shapes:

- `config_4tor.toml` — one physical Tofino2 hosting 4 logical ToRs, 1 uplink
  each.
- `config_4tor_2link.toml` — same, with 2 uplinks per ToR.

Both ship with **placeholder** hostnames, IPs, and MACs so they are safe to
keep in a public repository. To deploy against a real testbed, supply the
secret values through a private overlay:

```bash
cd openoptics/backends/tofino
cp secrets.local.toml.example secrets.local.toml   # fill in your testbed
python3 apply_secrets.py                           # generates *.local.toml
```

`apply_secrets.py` reads `secrets.local.toml` and writes
`config_4tor.local.toml` and `config_4tor_2link.local.toml` next to the
templates. Both the secrets file and the generated `.local.toml` files are
listed in `.gitignore` and never leave your machine. Pass a `.local.toml` as
`config_file=` in your deployment script.

The templates look like this (key sections, 2-link 4-ToR shown):

```toml
[sde]
path     = "/home/p4/bf-sde-9.12.0"
install  = "/home/p4/bf-sde-9.12.0/install"
build_p4 = true          # set false to skip P4 recompile when only Python changed

[bfrt]
port            = 50052  # BFRt gRPC port the daemon listens on
startup_timeout = 60

[bandwidth]
uplink_gbps     = 100
uplink_fec      = "NONE"
electrical_gbps = 100
server_gbps     = 100

[servers]
user     = "USER"
key_file = "~/.ssh/id_rsa"

[jump_host]                         # omit if switches are directly reachable
host            = "jumphost.example.com"
user            = "USER"
key_file        = "~/.ssh/id_rsa"
target_key_file = "~/.ssh/id_rsa"   # key *on the jump host* used to reach switches

[ocs_switch]
host = "OCS_SWITCH_IP"
user = "p4"

[[physical_switch]]
name = "tor-switch-1"
host = "TOR_SWITCH_IP"
user = "p4"

  [[physical_switch.logical_tor]]
  tor_id             = 0
  pipe_id            = 1            # which Tofino2 pipe hosts this logical ToR
  tor_ocs_port_pairs = [["7/0", "7/0"]]  # (ToR front-panel cage, OCS cage)
  server_ports       = ["1/0"]
  server_nic         = "enp23s0f1np1"
  server_mac         = "aa:bb:cc:dd:ee:01"
  host_ip            = "10.0.0.1"
  server_mgmt_ip     = "SERVER1_MGMT_IP"
```

**Field notes:**

- `build_p4 = false` skips `p4_build.sh` — use this when iterating on Python or
  setup scripts only.
- `tor_id` is the logical ToR id, as referenced by the Python API.
- `pipe_id` selects which hardware pipe of the physical switch hosts this
  logical ToR. Each pipe hosts at most one logical ToR.
- `tor_ocs_port_pairs` is a list of `(tor_cage, ocs_cage)` strings in
  `front-panel/lane` form. Its length **must equal `nb_link`** in the Python
  script; a mismatch produces physical-layer drops, since the routing table
  refers to links that are not wired.
- A `logical_tor` can attach a server by specifying the `server_*` and
  `host_*` fields. Servers can then send real traffic through the optical DCN
  (e.g. `ping`).

### 2.4 `BaseNetwork` parameters specific to Tofino

| Parameter | Type | Description |
|---|---|---|
| `backend` | str | `"Tofino"` |
| `nb_node` | int | Number of logical ToRs |
| `nb_link` | int | OCS uplinks per ToR — must match P4 `PORT_NUM` and `tor_ocs_port_pairs` length |
| `time_slice_duration_us` | int | Optical slice length, µs |
| `config_file` | str | Path to TOML |
| `skip_deploy` | bool | `True` to reuse already-running switches |
| `build_p4` | bool | Override `[sde].build_p4` |
| `remote_workdir` | str | Working dir on switches (default `/tmp/openoptics`) |
| `tofino_repo` | str | Override of the deployment package path on the switch |

---

## 3. System workflow

### 3.1 From Python to the wire

```
 dev container                  jump host                 switches
┌───────────────────┐       ┌──────────────┐       ┌──────────────────┐
│ BaseNetwork       │       │              │       │ OCS  switch      │
│  └ TofinoBackend  │──SSH──▶  paramiko    │──TCP──▶  bf_switchd (OCS)│
│     └ TofinoDeploy│       │  tunnel      │       └──────────────────┘
│        ThreadPool │       │              │       ┌──────────────────┐
│                   │       │              │──TCP──▶  bf_switchd (ToR)│
└───────────────────┘       └──────────────┘       │   pipe 0..3      │
                                                    └──────────────────┘
```

1. `BaseNetwork(backend="Tofino")` → `TofinoBackend.setup()` parses the TOML,
   builds the `logical_tor ↔ pipe` map and the `ip_to_tor` table, and creates a
   `TofinoDeployer`. **No SSH yet.**
2. `deploy_topo(circuits)` and `deploy_routing(paths, …)` call `load_table()`
   for each switch. The backend accumulates entries per switch; `clear_table()`
   is a no-op — the remote setup script wipes state on startup.
3. Once all ToR tables and the OCS table are ready, the backend writes the JSON
   config files (`openoptics_config.json`, `ocs_entries.json`,
   `tor_entries_tor{N}.json`) and invokes the deployer.
4. `TofinoDeployer` runs per-switch deployment in parallel
   (`ThreadPoolExecutor`):
   - SSH through the jump host (`direct-tcpip` channel; password fallback if
     key auth fails).
   - SCP the package (`emulated-ocs/` or `openoptics-tor/`), skipping binaries
     and precomputed tables.
   - If `build_p4` is set, run
     `$SDE/p4_build.sh openoptics_tor.p4 --with-tofino2 -D SLICE_NUM=<n> -D PORT_NUM=<nb_link>`.
   - `nohup ./run.sh … &` starts `bf_switchd` in daemon mode.
   - Poll BFRt gRPC on `:50052` until it accepts connections (bounded by
     `startup_timeout`).
   - Run `bfshell -b setup_{ocs,tor}.py` over SSH. The setup script reads
     `openoptics_config.json`, resolves front-panel cages to `dev_port`,
     populates tables, and configures port speeds and FEC.
5. `net.start()` opens the interactive CLI. `net.stop()` SSHs back to each
   switch and runs `pkill -9 -x openoptics_tor ocs bfshell bf_switchd`.

### 3.2 Runtime behavior

- **OCS** — pktgen generates rotation packets every `time_slice_duration_us`;
  the OCS ingress looks up `next_tor` and multicasts to all ToR-facing ports,
  so every ToR observes the slice boundary synchronously.
- **ToR** — each rotation signal advances `cur_slice`. Data packets hit
  `time_flow_table`, keyed on `(cur_slice, dst_group)` →
  `(port, send_slice, next_tor, alternate_port, alternate_slot,
  alternate_next_tor)`. If the primary port's queue depth exceeds
  `p{i}_max_lossless_qdepth_reg`, ADM reroutes to the alternate. AFC
  pause/resume control words are pre-staged in `set_afc_tb` so upstream ports
  pause before queues overflow.
- **VLB** — two generic sentinels in `routing.p4` (not VLB-specific):
  `send_port == 0xff` → `tb_random_to_port` picks a port;
  `send_slice == 255` → `cal_port_slice_to_node` resolves a node to
  `(port, slice)`.
- **Source routing** — an `optics_sr` header carries a hop list (≤ 2 hops).
  Each hop is consumed at the relevant ToR.

### 3.3 Key files

| Layer | File |
|---|---|
| Python backend | [`openoptics/backends/tofino/backend.py`](../openoptics/backends/tofino/backend.py) |
| Deployment orchestrator | [`openoptics/backends/tofino/deploy.py`](../openoptics/backends/tofino/deploy.py) |
| OCS P4 + setup | [`openoptics/backends/tofino/emulated-ocs/`](../openoptics/backends/tofino/emulated-ocs/) |
| ToR P4 + setup | [`openoptics/backends/tofino/openoptics-tor/`](../openoptics/backends/tofino/openoptics-tor/) |
| Configs | `config_4tor.toml`, `config_4tor_2link.toml`, `config_2tor_2link.toml` |

