# Tofino Backend — Internals and Known Gaps

Audience: contributors working on the Tofino backend. User-facing documentation
lives in [tofino-backend.md](tofino-backend.md); this file collects the
non-obvious traps and the current open work items.

---

## 1. Technical highlights

Non-obvious things that will bite you if you don't know them.

### 1.1 Pktgen-lookahead parser collision

The ToR parser branches on the **low nibble of the first Ethernet byte** —
that's where Tofino pktgen encodes `app_id`. Values 1..7 route the packet into
the pktgen branch, consuming the pktgen header as a routing header. Any real
MAC whose first-byte low nibble ∈ {1..7} gets misparsed.

> When installing static ARP on servers, use `de:ad:be:ef:de:ad` (low nibble
> `0xe`). Avoid `0x?1`..`0x?7` as the first byte's low nibble.

### 1.2 Two generic sentinels, not VLB-specific

`routing.p4` interprets:

- `send_port == 0xff` → draw a random port from `tb_random_to_port`.
- `send_slice == 255`  → resolve node via `cal_port_slice_to_node` to
  `(port, slice)`.

Random VLB combines both. Any future feature that needs random port or
node-indexed resolution reuses the same machinery — don't bolt on a parallel
mechanism.

### 1.3 `nb_link` must match the wiring

A 2-port P4 binary on a 1-wire physical setup drops ≈50 % of packets at the
physical layer, exactly mimicking a PHV or scheduling bug. Before debugging
anything in the data plane, verify:

- `PORT_NUM` the P4 was compiled with,
- `nb_link` in the Python script,
- `len(tor_ocs_port_pairs)` in the TOML,

are all equal, and every listed cage is physically wired.

### 1.4 `RegisterAction` `$ena` gateway insertion

Multiple `RegisterAction`s on the same `Register` — even in disjoint `if`
branches — force the compiler to insert a runtime gateway ensuring one execution
per packet, disabling all but one action. Symptom: registers stuck at 0.

Workaround used in [`queue.p4`](../openoptics/backends/tofino/openoptics-tor/p4src/queue.p4):
merge into a single `RegisterAction` that branches internally on
`is_new_slice`.

To detect this, grep the compiler output:

```bash
grep -c  "<reg_name>\$ena" <bfa_file>
grep -B2 -A8 "<reg_name>\$ena" <bfa_file>
```

in `build/p4-build/tofino2/<program>/<pipe>/<program>.bfa`.

### 1.5 AFC queue-depth observability

The drain logic fires every 50 ns at 100 Gb/s (≈625 B drained per tick). A
single `bfshell` `dump()` is many orders of magnitude slower, so registers
usually read 0.

To observe non-zero values, either:

- Lower `qdiff` to `1` in `setup_tor.py` → drain becomes ≈31 ms; or
- Raise `p0_max_qdepth` (`set_default(value=625000000)`) → non-zero values hold
  for ≈50 ms.

Then poll with `dump(pipe=<id>, from_hw=True)` (asymmetric tables **require**
`pipe=`, else you get `Invalid pipe 65535`).

### 1.6 Source routing is capped at 2 hops

The backend validates hop-list length before deploying; >2 hops raises
`ValueError`. The cap is a PHV packing constraint on the `optics_sr` header, not
an algorithmic one.

### 1.7 Guardband slices are required

`setup_util.find_pause_slice()` walks the schedule looking for a guardband slot.
Schedules without one fail with `-1 is not in list`. Generate with
`OpticalTopo.opera(..., guardband=True)` (same for `shale`).

### 1.8 `bfshell` single-instance lock

Only one `bfrt_python` shell can own the switch at a time. If deployment fails
with `Only one Python shell instance allowed at a time`, a stale `bfshell` or
`bf_switchd` is holding the lock. Recover:

```bash
sudo pkill -9 -x bfshell; sudo pkill -9 -x bf_switchd
```

`net.stop()` does this automatically on a clean exit.

### 1.9 Inspecting the compiled P4

When routing misbehaves in ways that don't match the source, open the `.bfa`:

```
build/p4-build/tofino2/<program>/<program>/tofino2/<pipe>/<program>.bfa
```

Useful starting points:

- `grep -n "^stage\|<table_name>"` — find the stage a table landed in.
- `grep "\$ena"` — compiler-inserted gateways (see §1.4).
- Search for the exact match-key name to see how the compiler packed PHV
  containers for it.

---

## 2. Known gaps

- **`tests/live_2tor_test.py`** is referenced in `CLAUDE.md` as the canonical
  end-to-end test, but it is not yet in the repo. Landing it is the next task.
- **Rank table refactor**: `tb_compute_p{i}_rank` is currently next-hop-keyed.
  Migrating to `send_slice`-keyed is cleaner and fixes rank for random VLB, but
  the current code works at 100 % so the refactor is deferred.
- **Source routing hop limit**: capped at 2 hops (§1.6). Longer paths require a
  different header layout.
- **Bandwidth/FEC**: only the homogeneous 100 G / FEC-NONE profile is exercised;
  mixed-rate fabrics are untested.
