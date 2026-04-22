# Tofino Backend

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
| Dashboard for collecting testbed telemetry (queue depth, drops, per-slice stats) | 🚧 TODO |

Examples live under `examples/`: `tofino_4node_1link_direct.py`,
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
| SSH access | Key-based SSH from your workstation to all switches (directly or via a jump host). Jump host needs a key on disk that can reach the switches. |

### 2.2 Quick start

Install the package and generate a config template in your project directory:

```bash
pip install "openoptics-dcn[tofino]"
cd ~/my-testbed
openoptics-gen-config                 # writes ./openoptics-tofino.toml
# edit openoptics-tofino.toml to fill in USER, jumphost.example.com,
# IPs, MACs, etc. for your testbed (see §2.3)
```

Then reference that file as `config_file=` in your deployment script:

```python
from openoptics import Toolbox, OpticalTopo, OpticalRouting

net = Toolbox.BaseNetwork(
    name="tofino_4node_2link_direct",
    backend="Tofino",           # only change from Mininet
    nb_node=4,
    nb_link=2,
    time_slice_duration_us=50,
    config_file="openoptics-tofino.toml",
)

circuits = OpticalTopo.opera(nb_node=4, nb_link=2, guardband=True)
net.deploy_topo(circuits)

paths = OpticalRouting.routing_direct(net.get_topo())
net.deploy_routing(paths, routing_mode="Per-hop")

net.start()   # opens the OpenOptics CLI
```

You can also grab a bundled Tofino example to start from:

```bash
openoptics-gen-examples                    # copies examples/ into cwd
python3 examples/tofino_4node_2link_direct.py
```

The Tofino backend runs from a plain Python environment — no Docker image is
needed, since the SDE and P4 toolchain live on the switches and are invoked
over SSH. `pip install "openoptics-dcn[tofino]"` pulls in `paramiko` (and
`tomli` on Python < 3.11); that's the full dependency set on the workstation
side.

In the CLI:

```
server_check           # bring up NICs, set IPs, install ARP on both servers
server_ping 0 1        # ping from server on ToR 0 to server on ToR 1
h0 ping h1             # same, via hN shorthand
```

Press `Ctrl-D` to exit; `net.stop()` runs automatically and kills the remote
processes (`pkill -9`).

### 2.3 Config file

The backend reads a TOML config passed via `config_file=`. The easiest way to
start is:

```bash
openoptics-gen-config                  # writes ./openoptics-tofino.toml
openoptics-gen-config -o my.toml       # different destination
openoptics-gen-config --force          # overwrite an existing file
```

`openoptics-gen-config` copies the bundled template (a 4-ToR / 1-uplink
topology) into your working directory. Edit it in place with your testbed's
real hostnames, IPs, and MACs. The file contains **placeholder** values like
`USER`, `jumphost.example.com`, `OCS_SWITCH_IP`, `aa:bb:cc:dd:ee:01`,
`10.0.0.1` — search-and-replace those with real values before deploying.

The default template describes the following layout:

```
tor-switch-1 (Tofino2, one pipe per logical ToR)        ocs-switch (Tofino2)
┌──────────────────────────────────────────────┐        ┌──────────────┐
│ server1 ── 1/0  ┌─ ToR0 (pipe 1) ──  7/0 ────┼────────┼─ 7/0         │
│ server2 ── 9/0  ├─ ToR1 (pipe 2) ── 15/0 ────┼────────┼─ 15/0        │
│                 ├─ ToR2 (pipe 3) ── 23/0 ────┼────────┼─ 23/0        │
│                 └─ ToR3 (pipe 0) ── 31/0 ────┼────────┼─ 31/0        │
└──────────────────────────────────────────────┘        └──────────────┘
```

For a 2-uplinks-per-ToR testbed, start from the same template
(`openoptics-tofino.toml`) and duplicate each `tor_ocs_port_pairs` entry to
list both uplink port pairs per ToR:

```
tor-switch-1 (Tofino2)                                  ocs-switch (Tofino2)
┌──────────────────────────────────────────────┐        ┌──────────────┐
│ server1 ── 1/0  ┌─ ToR0 ──  7/0, 8/0 ────────┼────────┼─ 7/0,  8/0   │
│ server2 ── 9/0  ├─ ToR1 ── 15/0, 16/0 ───────┼────────┼─ 15/0, 16/0  │
│                 ├─ ToR2 ── 23/0, 24/0 ───────┼────────┼─ 23/0, 24/0  │
│                 └─ ToR3 ── 31/0, 32/0 ───────┼────────┼─ 31/0, 32/0  │
└──────────────────────────────────────────────┘        └──────────────┘
```

Your filled-in config file should never be checked into a public repo — add
it to your project's `.gitignore`.

The template looks like this (key sections, 4-ToR / 1-uplink shown):

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

### 2.4 `BaseNetwork` parameters for a Tofino deployment

"Common" parameters are shared with other backends (Mininet, ns-3); "Tofino"
parameters are only accepted when `backend="Tofino"` (they flow through
`**backend_kwargs` and are validated against `TofinoBackend.accepted_kwargs()`).
The table lists the parameters most relevant to a Tofino run — see
`BaseNetwork.__init__` for the full common set (e.g. `nb_host_per_tor`,
`arch_mode`, `guardband_ms`, `use_webserver`, `ocs_tor_link_bw`).

| Parameter | Type | Scope | Description |
|---|---|---|---|
| `backend` | str | Common | `"Tofino"` |
| `nb_node` | int | Common | Number of logical ToRs |
| `nb_link` | int | Common | OCS uplinks per ToR — must match P4 `PORT_NUM` and `tor_ocs_port_pairs` length |
| `time_slice_duration_us` | int | Common | Optical slice length, µs |
| `config_file` | str | Tofino | Path to TOML |
| `skip_deploy` | bool | Tofino | `True` to reuse already-running switches |
| `build_p4` | bool | Tofino | Override `[sde].build_p4` |
| `remote_workdir` | str | Tofino | Working dir on switches (default `/tmp/openoptics`) |
| `tofino_repo` | str | Tofino | Override of the deployment package path on the switch |

---

## 3. System workflow

### 3.1 From Python to the wire

```
 workstation                   jump host                 switches
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

- **Emulated OCS** — a Tofino2 stands in for a real optical circuit switch.
  Pktgen generates rotation packets every `time_slice_duration_us`; the OCS
  ingress looks up `next_tor` and multicasts to all ToR-facing ports, so
  every ToR observes the slice boundary synchronously.
- **ToR data plane** — each rotation signal advances `cur_slice`. Data packets
  hit `time_flow_table`, keyed on `(cur_slice, dst_group)` →
  `(port, send_slice, next_tor, alternate_port, alternate_slot,
  alternate_next_tor)`. If the primary port's queue depth exceeds
  `p{i}_max_lossless_qdepth_reg`, ADM reroutes to the alternate. AFC
  pause/resume control words are pre-staged in `set_afc_tb` so upstream ports
  pause before queues overflow.
- **Routing modes** — selectable via `deploy_routing(..., routing_mode=...)`.
  `"Per-hop"`: each ToR on the path independently looks up its own
  `time_flow_table`. `"Source"`: the ingress ToR attaches an `optics_sr`
  header carrying the full hop list (≤ 2 hops); each downstream ToR consumes
  one hop as the packet traverses the path.
- **Next-node-based forwarding** — a `time_flow_table` entry can name a
  target node instead of encoding an exact slot. The sentinel
  `send_slice == 255` triggers `cal_port_slice_to_node`, which resolves the
  named node to a concrete `(port, send_slice)` pair at forwarding time using
  the current schedule. Both the egress port and send slice are chosen at
  runtime rather than baked into the entry.
- **Random-port forwarding** — entries with `send_port == 0xff` trigger
  `tb_random_to_port`, which picks an egress port uniformly at random and
  sends in the current slice (e.g. VLB's randomized first hop to spread load
  across uplinks).

The last two are orthogonal to the routing mode and can appear in per-hop or
source-routed paths.