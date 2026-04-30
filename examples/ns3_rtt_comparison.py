"""Compare per-flow end-to-end delay across optical-DCN architectures.

For every architecture and every directed host pair ``(src, dst)`` with
``src != dst``, installs ``NUM_FLOWS_PER_PAIR`` short concurrent UDP
flows. Each flow sends ``PACKETS_PER_FLOW`` packets at ``INTERVAL_US``
spacing. After the simulation, ns-3's ``FlowMonitor`` (already wired up
by the backend) reports per-flow stats: average / min / max one-way
delay, FCT, packet counts. Each flow contributes one row, so the
per-architecture CDF has ``NB_PAIRS × NUM_FLOWS_PER_PAIR`` points (e.g.
56 × 20 = 1120 for ``NB_NODE=8``).

Outputs (cwd):
    rtt_comparison.csv   long format, one row per flow:
                         arch, src, dst, flow_idx, delay_avg_ms,
                         delay_min_ms, delay_max_ms, fct_ms,
                         tx_packets, rx_packets, lost_packets
    rtt_comparison.json  wide format, per-architecture parallel arrays.
    rtt_cdfs.pdf         publication-style CDF plot generated from the JSON.

To regenerate only the plot, run ``python3 examples/plot_ns3_rtt_cdf.py``.

Note: this is one-way delay (FlowMonitor's ``delaySum / rxPackets``),
not round-trip RTT. For architecture comparisons one-way delay carries
the same ranking signal as RTT and avoids the per-packet probe
machinery.
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List

from openoptics import OpticalRouting, OpticalTopo, Toolbox

try:
    from .plot_ns3_rtt_cdf import DEFAULT_OUTPUT_PATH, plot_rtt_cdf
except ImportError:
    _EXAMPLES_DIR = str(Path(__file__).resolve().parent)
    if _EXAMPLES_DIR not in sys.path:
        sys.path.insert(0, _EXAMPLES_DIR)
    from plot_ns3_rtt_cdf import DEFAULT_OUTPUT_PATH, plot_rtt_cdf


# --------------------------------------------------------------------- config

NB_NODE = 8
NB_LINK = 4
TIME_SLICE_US = 50
SIMULATION_STOP_S = 10
NUM_FLOWS_PER_PAIR = 100         # concurrent flows per directed (src, dst)
PACKETS_PER_FLOW = 1          # packets each flow sends
INTERVAL_US = 10                # spacing between packets within a flow
PACKET_SIZE = 64
OCS_TOR_LINK_BW_GBPS = 100
TOR_HOST_LINK_BW_GBPS = 100
SRC_NODES = range(NB_NODE)
DST_NODES = range(NB_NODE)

# Pairs are serialized: each (src, dst) gets a back-to-back time slot so
# different pairs don't compete on shared uplink/downlink. Inside a pair's
# slot, NUM_FLOWS_PER_PAIR flows start together; this is concurrent fan-out
# from one source to one destination, which is what we want to measure.
#
# PROBE_DRAIN_US is the gap between the end of one pair's burst
# (PACKETS_PER_FLOW * INTERVAL_US) and the start of the next — long enough
# for the last packet to drain before the next pair begins.
PROBE_DRAIN_US = 5_000          # 5 ms drain between pairs
PROBE_BASE_START_S = 0.05       # first pair kicks off at 50 ms


@dataclass
class Scenario:
    label: str
    topo: Callable                  # () -> circuits
    # (net) -> paths. Takes the BaseNetwork so routing functions that need
    # tor_to_ocs_port (e.g. routing_vlb) can read it off net.tor_ocs_ports.
    routing: Callable
    routing_mode: str               # "Per-hop" or "Source"


SCENARIOS: List[Scenario] = [
    Scenario(
        label="opera + routing_direct (perhop)",
        topo=lambda: OpticalTopo.opera(nb_node=NB_NODE, nb_link=NB_LINK),
        routing=lambda net: OpticalRouting.routing_direct(net.get_topo()),
        routing_mode="Per-hop",
    ),
    Scenario(
        label="opera + routing_vlb (src)",
        topo=lambda: OpticalTopo.opera(nb_node=NB_NODE, nb_link=NB_LINK),
        routing=lambda net: OpticalRouting.routing_vlb(
            net.get_topo(), net.tor_ocs_ports,
        ),
        routing_mode="Source",
    ),
    Scenario(
        label="opera + routing_hoho (perhop)",
        topo=lambda: OpticalTopo.opera(nb_node=NB_NODE, nb_link=NB_LINK),
        routing=lambda net: OpticalRouting.routing_hoho(net.get_topo()),
        routing_mode="Per-hop",
    ),
    Scenario(
        label="opera + routing_hoho (src)",
        topo=lambda: OpticalTopo.opera(nb_node=NB_NODE, nb_link=NB_LINK),
        routing=lambda net: OpticalRouting.routing_hoho(net.get_topo()),
        routing_mode="Source",
    ),
]


# --------------------------------------------------------------------- runner

def run_scenario(s: Scenario) -> dict:
    """Build a fresh BaseNetwork for ``s``, install flows, return stats."""
    net = Toolbox.BaseNetwork(
        name=f"ns3_delay_{s.label}",
        backend="ns3",
        nb_node=NB_NODE,
        nb_link=NB_LINK,
        time_slice_duration_us=TIME_SLICE_US,
        # Reserve ~2 µs at the end of each slot so the same-slice send
        # cascade (1 µs ToR→OCS + 1 µs OCS→ToR per hop) on multi-hop
        # source-routed paths can't push the last OCS receive past the
        # slot boundary; without this, source-routed packets late in a
        # slot get routed by the next slot's OCS schedule and end up at
        # the wrong ToR.
        guardband_us=2,
        ocs_tor_link_bw_gbps=OCS_TOR_LINK_BW_GBPS,
        tor_host_link_bw_gbps=TOR_HOST_LINK_BW_GBPS,
        # Per-hop admission control: when an outgoing slot is too full to
        # drain this packet within its active window, walk
        # (dst, arrival_ts+offset) and pick the first slot that fits — so
        # late-in-slot packets reroute to a near-future slot instead of
        # falling through to the calendar queue and waiting a full
        # schedule cycle. Only effective for the per-hop scenarios; SR
        # mode goes through HandleSourceRoutedUplink which doesn't
        # consult ADM.
        admission_control=True,
        use_webserver=False,
        simulation_stop_s=SIMULATION_STOP_S,
    )
    try:
        assert net.deploy_topo(s.topo())
        paths = s.routing(net)
        assert net.deploy_routing(paths, routing_mode=s.routing_mode)

        # NUM_FLOWS_PER_PAIR flows per directed pair (src != dst). Within a
        # pair's slot, flows are spaced INTERVAL_US apart so the source ToR
        # uplink isn't asked to drain all flows' first packets at the same
        # simulated instant (otherwise the per-slice byte budget rejects
        # them as ForwardSendFail). Different pairs are serialized so they
        # don't compete on shared uplink/downlink. The traffic builder
        # auto-allocates a unique UDP port per flow.
        pairs = [(a, b) for a in SRC_NODES for b in DST_NODES if a != b]
        flow_burst_us = PACKETS_PER_FLOW * INTERVAL_US
        pair_burst_us = NUM_FLOWS_PER_PAIR * INTERVAL_US + flow_burst_us
        slot_us = pair_burst_us + PROBE_DRAIN_US
        total_window_s = (
            PROBE_BASE_START_S + len(pairs) * slot_us / 1e6
        )
        if total_window_s > SIMULATION_STOP_S:
            raise RuntimeError(
                f"SIMULATION_STOP_S={SIMULATION_STOP_S}s too small for "
                f"{len(pairs)} serialized pairs: need ≥ {total_window_s:.3f}s "
                f"(pair burst {pair_burst_us} us + drain {PROBE_DRAIN_US} us "
                f"per pair). Raise SIMULATION_STOP_S, lower "
                f"NUM_FLOWS_PER_PAIR, or lower PACKETS_PER_FLOW * INTERVAL_US."
            )

        udp_gen = net.udp_traffic()
        for i, (src, dst) in enumerate(pairs):
            pair_start_s = PROBE_BASE_START_S + i * slot_us / 1e6
            for f in range(NUM_FLOWS_PER_PAIR):
                udp_gen.flow(
                    src=src, dst=dst,
                    num_packets=PACKETS_PER_FLOW,
                    interval_s=INTERVAL_US / 1e6,
                    packet_size_bytes=PACKET_SIZE,
                    start_s=pair_start_s + f * INTERVAL_US / 1e6,
                )
        installed = udp_gen.install()
        net.start()

        delay_avg_ms: List[float] = []
        delay_min_ms: List[float] = []
        delay_max_ms: List[float] = []
        fct_ms: List[float] = []
        tx_packets: List[int] = []
        rx_packets: List[int] = []
        lost_packets: List[int] = []
        srcs: List[int] = []
        dsts: List[int] = []
        flow_idxs: List[int] = []
        # The install loop appended NUM_FLOWS_PER_PAIR flows per pair, in
        # order; flow_idx is the flow's position within its pair.
        per_pair_counter: dict = {}
        for inst in installed:
            stats = inst.stats()
            if stats is None or stats.rx_packets == 0:
                continue
            key = (inst.spec.src, inst.spec.dst)
            flow_idx = per_pair_counter.get(key, 0)
            per_pair_counter[key] = flow_idx + 1
            srcs.append(inst.spec.src)
            dsts.append(inst.spec.dst)
            flow_idxs.append(flow_idx)
            delay_avg_ms.append(stats.delay_avg_s * 1e3)
            delay_min_ms.append(stats.delay_min_s * 1e3)
            delay_max_ms.append(stats.delay_max_s * 1e3)
            fct_ms.append(stats.fct_s * 1e3)
            tx_packets.append(stats.tx_packets)
            rx_packets.append(stats.rx_packets)
            lost_packets.append(stats.lost_packets)
        return {
            "src": srcs, "dst": dsts, "flow_idx": flow_idxs,
            "delay_avg_ms": delay_avg_ms,
            "delay_min_ms": delay_min_ms,
            "delay_max_ms": delay_max_ms,
            "fct_ms": fct_ms,
            "tx_packets": tx_packets,
            "rx_packets": rx_packets,
            "lost_packets": lost_packets,
        }
    finally:
        # Tear down simulator + IP allocation state before the next scenario,
        # whether or not this one succeeded. ns-3's Ipv4AddressGenerator is
        # a process-wide singleton that keeps every allocated address; without
        # Reset() the next BaseNetwork hits "Address Collision: 10.0.0.1"
        # as a NS_FATAL the second time a scenario tries to assign a host IP.
        try:
            from ns import ns
            ns.Simulator.Destroy()
            ns.Ipv4AddressGenerator.Reset()
        except Exception:
            pass
        try:
            net._backend.cleanup()
        except Exception:
            pass


def _percentile(sorted_vals: List[float], q: float) -> float:
    """Nearest-rank percentile, stdlib-only."""
    if not sorted_vals:
        return float("nan")
    k = min(len(sorted_vals) - 1, max(0, int(q * (len(sorted_vals) - 1))))
    return sorted_vals[k]


def _summarize(values: List[float]) -> dict:
    if not values:
        return {
            "n": 0, "min": float("nan"), "p50": float("nan"),
            "p99": float("nan"), "max": float("nan"), "stdev": float("nan"),
        }
    srt = sorted(values)
    return {
        "n": len(values),
        "min": srt[0],
        "p50": _percentile(srt, 0.50),
        "p99": _percentile(srt, 0.99),
        "max": srt[-1],
        "stdev": statistics.pstdev(values) if len(values) > 1 else 0.0,
    }


def _print_summary(results: dict) -> None:
    print()
    print(
        f"  {'Architecture':<40}{'N':>6}{'min':>9}{'p50':>9}"
        f"{'p99':>9}{'max':>9}{'std':>9}   (per-flow delay_avg, ms)"
    )
    print("  " + "-" * 91)
    for label, data in results.items():
        s = _summarize(data["delay_avg_ms"])
        print(
            f"  {label:<40}{s['n']:>6}"
            f"{s['min']:>9.3f}{s['p50']:>9.3f}"
            f"{s['p99']:>9.3f}{s['max']:>9.3f}{s['stdev']:>9.3f}"
        )
    print()


def _write_csv(path: str, results: dict) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "arch", "src", "dst", "flow_idx",
            "delay_avg_ms", "delay_min_ms", "delay_max_ms",
            "fct_ms", "tx_packets", "rx_packets", "lost_packets",
        ])
        for label, data in results.items():
            for src, dst, fi, d_avg, d_min, d_max, fct, tx, rx, lost in zip(
                data["src"], data["dst"], data["flow_idx"],
                data["delay_avg_ms"], data["delay_min_ms"], data["delay_max_ms"],
                data["fct_ms"], data["tx_packets"], data["rx_packets"],
                data["lost_packets"],
            ):
                w.writerow([
                    label, src, dst, fi,
                    f"{d_avg:.6f}", f"{d_min:.6f}", f"{d_max:.6f}",
                    f"{fct:.6f}", tx, rx, lost,
                ])


def _write_json(path: str, results: dict) -> None:
    out = {
        "meta": {
            "nb_node": NB_NODE,
            "nb_link": NB_LINK,
            "time_slice_duration_us": TIME_SLICE_US,
            "simulation_stop_s": SIMULATION_STOP_S,
            "num_flows_per_pair": NUM_FLOWS_PER_PAIR,
            "packets_per_flow": PACKETS_PER_FLOW,
            "interval_us": INTERVAL_US,
            "packet_size_bytes": PACKET_SIZE,
            "ocs_tor_link_bw_gbps": OCS_TOR_LINK_BW_GBPS,
            "tor_host_link_bw_gbps": TOR_HOST_LINK_BW_GBPS,
        },
        "architectures": results,
    }
    with open(path, "w") as f:
        json.dump(out, f, indent=2)


# ----------------------------------------------------------------------- main

if __name__ == "__main__":
    results = {}
    for s in SCENARIOS:
        print(f"[delay] running {s.label} ...", flush=True)
        try:
            results[s.label] = run_scenario(s)
        except Exception as exc:  # keep going so one bad scenario doesn't abort the sweep
            print(f"[delay]   failed: {exc}", flush=True)
            results[s.label] = {
                "src": [], "dst": [], "flow_idx": [],
                "delay_avg_ms": [], "delay_min_ms": [], "delay_max_ms": [],
                "fct_ms": [], "tx_packets": [], "rx_packets": [],
                "lost_packets": [],
            }

    _print_summary(results)
    _write_csv("rtt_comparison.csv", results)
    _write_json("rtt_comparison.json", results)
    print("  wrote rtt_comparison.csv  (long format, one row per flow)")
    print("  wrote rtt_comparison.json (wide format, per-architecture arrays)")
    plot_path = plot_rtt_cdf(input_path="rtt_comparison.json")
    if plot_path is not None:
        print(f"  wrote {plot_path} (PDF delay CDF)")
    else:
        print(f"  skipped {DEFAULT_OUTPUT_PATH}; install matplotlib to enable plotting")
