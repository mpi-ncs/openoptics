# Emulated OCS

Optical Circuit Switch (OCS) emulation running on Intel Tofino/Tofino2. A single physical switch emulates the OCS role in the optical data center network, working in conjunction with [openoptics-tor](../openoptics-tor/).

## Role in the System

```
 ToR 0 ──┐
 ToR 1 ──┤
 ToR 2 ──┤  emulated-ocs  (this module)
 ToR 3 ──┤    - Forward optics packets to the next-hop ToR
 ToR 4 ──┤    - Broadcast rotation (pause/resume) signals to all ToRs
 ToR 5 ──┤      for slice-transition synchronization
 ToR 6 ──┤
 ToR 7 ──┘
```

The OCS does not schedule traffic. It provides two services:
1. **Optical forwarding** — `ETHERTYPE_OPTICS` packets are forwarded to the next-hop ToR based on the `next_tor` field in the optics L2 header.
2. **Circuit signaling** — periodic `ETHERTYPE_ROTATION` packets are multicast to all connected ToRs to trigger slice transitions.

## Requirements

- Intel Barefoot SDE 9.12.0
- `SDE` and `SDE_INSTALL` environment variables set

## Usage

```bash
./run.sh <duration>
```

| Parameter  | Valid values |
|------------|-------------|
| `duration` | `1us` `2us` `10us` `25us` `50us` `100us` `500us` |

Example:
```bash
./run.sh 50us
```

The `run.sh` script handles building, environment setup, and launching the binary with `sudo -E` to preserve SDE variables.

## Data Plane (P4)

**Source**: `p4src/ocs.p4`

### Ingress Parser

Detects pktgen packets by `app_id` lookahead before parsing Ethernet:

| `app_id` | Constant | Treatment |
|---|---|---|
| `3` | `PKTGEN_APP_ID_ROTATION` | Strip pktgen header, parse Ethernet |
| `7` | `PKTGEN_APP_ID_KICKOFF` | Strip pktgen header, parse Ethernet |
| other | — | Parse Ethernet directly |

After Ethernet, the parser selects on EtherType:

| EtherType | Constant | Action |
|---|---|---|
| `0x3001` | `ETHERTYPE_ROTATION` | Accept (no further parsing) |
| `0x3000` | `ETHERTYPE_OPTICS` | Parse `optics_l2` header |
| `0x0800` | `ETHERTYPE_IPV4` | Accept |
| `0x86dd` | `ETHERTYPE_IPV6` | Accept |

### Ingress Control

| Packet type | Forwarding action |
|---|---|
| `ETHERTYPE_ROTATION` | Multicast to all ToR-facing ports (`MCAST_GRP_ID = 1`) |
| `ETHERTYPE_OPTICS` | Unicast via `ocs` table keyed on `optics_l2.next_tor` |
| IPv4 / IPv6 | Unicast via `ocs` table keyed on `ethernet.dst_addr` |

The `ocs` table (128 entries) maps a MAC address to a physical egress port. Egress pipeline is bypassed.

### Key Constants

| Constant | Value | Description |
|---|---|---|
| `SLICE_NUM` | 16 | Slots per schedule cycle (matches openoptics-tor) |
| `ETHERTYPE_OPTICS` | 0x3000 | Optics-encapsulated data frame |
| `ETHERTYPE_ROTATION` | 0x3001 | Slice transition signal (multicast) |
| `PKTGEN_APP_ID_KICKOFF` | 7 | Pktgen kickoff app |
| `PKTGEN_APP_ID_ROTATION` | 3 | Pktgen rotation timer app |
| `MCAST_GRP_ID` | 1 | Multicast group for rotation broadcast |

## Control Plane (C++)

**Source**: `ocs.cpp`

### Initialization Sequence

1. Parse `<duration>` CLI argument; convert to nanoseconds (`slice_duration = duration × 1000`).
2. **`init_bf_switchd("ocs")`** — loads P4 program from `$SDE_INSTALL/share/p4/targets/tofino2/ocs.conf`.
3. **`init_tables(duration)`** — writes `/tmp/bfrt_ocs_setup_wrapper.py` that injects `SLICE_DURATION` into the Python env, then runs `setup_ocs.py` via `bfshell -b`.
4. Sleep 2 s for table population to complete.
5. **`set_rotation_pktgen()`** — starts periodic rotation signal generation.
6. Drops into interactive `bfshell`.

### Pktgen Application

| App | ID | Mode | Period | Purpose |
|---|---|---|---|---|
| Rotation | `PKTGEN_APP_ID_ROTATION` (3) | Periodic | `slice_duration` ns | Generates `ETHERTYPE_ROTATION` packets broadcast to all ToRs |
| Kickoff | `PKTGEN_APP_ID_KICKOFF` (7) | Periodic | 50 ms | Available for one-shot AFC initialization (called on demand) |

The rotation app fires with `batch_count = 7` (8 batches per cycle, one per pair of slices), one packet per batch at `ipg = slice_duration`.

## Python Configuration

**Source**: `setup_ocs.py`

Reads `SLICE_DURATION` from the environment (injected by the C++ wrapper) and configures the switch:

1. **`clear_all()`** — clears all match, register, selector, and action-profile tables.
2. **Port configuration** — enables all 32 front-panel ports at 100G.
3. **`ocs` table** — populates MAC → egress port entries for all 8 ToR destinations.
4. **Multicast group** — defines the `MCAST_GRP_ID = 1` group covering all ToR-facing uplink dev_ports for rotation signal broadcast.

### Port Mapping (ocs table)

| dst MAC | Dev port | Front-panel | Destination |
|---|---|---|---|
| `0x000000000011` | 400 | 17/0 | ToR group A |
| `0x000000000012` | 432 | 21/0 | ToR group A |
| `0x000000000013` | 56 | 25/0 | ToR group A |
| `0x000000000010` | 24 | 29/0 | ToR group A |
| `0x000000000015` | 136 | 1/0 | ToR group B |
| `0x000000000016` | 168 | 5/0 | ToR group B |
| `0x000000000017` | 320 | 9/0 | ToR group B |
| `0x000000000014` | 288 | 13/0 | ToR group B |

### Multicast (Rotation Broadcast)

The rotation signal multicast group includes all ToR-facing uplink ports:

```
160 (4/0), 192 (8/0), 296 (12/0), 264 (16/0),
408 (20/0), 440 (24/0), 48 (28/0), 16 (32/0)
```

## Directory Structure

```
emulated-ocs/
├── p4src/
│   ├── ocs.p4                # Top-level ingress pipeline
│   └── common/
│       ├── headers.p4        # Header definitions and shared constants
│       └── util.p4           # Tofino parser boilerplate
├── ocs.cpp                   # C++ control plane source
├── setup_ocs.py              # BFRt Python table configuration script
├── Makefile                  # Build rules
└── run.sh                    # Entry point: build + run with duration arg
```
