"""Compare TCP long-flow FCT across flow sizes on a circular traffic matrix.

For every architecture and every configured flow size, installs one TCP
BulkSend flow on each directed ring edge:

    0->1, 1->2, 2->3, ..., 7->0

Each flow contributes one row of FlowMonitor statistics. The script also
aggregates average FCT by ``(architecture, flow_size_bytes)`` and writes a PDF
figure with flow size on the x-axis and average FCT on the y-axis.

Outputs (cwd):
    tcp_circle_long_flows.csv   one row per TCP ring flow
    tcp_circle_long_flows.json  per-architecture parallel arrays
    tcp_circle_fct_by_size.csv  one summary row per architecture/size
    tcp_circle_fct_by_size.pdf  average-FCT figure
"""

from __future__ import annotations

import csv
import argparse
import json
import math
import os
import subprocess
import statistics
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from openoptics import OpticalRouting, OpticalTopo, Toolbox


# --------------------------------------------------------------------- config

NB_NODE = 8
NB_LINK = 4
TIME_SLICE_US = 50
SIMULATION_STOP_S = 0.7
TCP_START_S = 0.05
TCP_STOP_S = 0.65
FLOW_SIZE_BYTES = [128_000, 256_000, 512_000, 1_000_000, 2_000_000]
TCP_CHUNK_SIZE_BYTES = 1448
OCS_TOR_LINK_BW_GBPS = 100
TOR_HOST_LINK_BW_GBPS = 1

RAW_CSV_PATH = "tcp_circle_long_flows.csv"
RAW_JSON_PATH = "tcp_circle_long_flows.json"
SUMMARY_CSV_PATH = "tcp_circle_fct_by_size.csv"
FCT_PLOT_PATH = "tcp_circle_fct_by_size.pdf"

RING_PAIRS = [(i, (i + 1) % NB_NODE) for i in range(NB_NODE)]

_COLORS = (
    "#0072B2",
    "#D55E00",
    "#009E73",
    "#CC79A7",
    "#E69F00",
    "#56B4E9",
    "#000000",
)
_MARKERS = ("o", "s", "^", "D", "v", "P", "X")


@dataclass
class Scenario:
    label: str
    topo: Callable
    routing: Callable
    routing_mode: str


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

def run_scenario(s: Scenario, flow_size_bytes: int) -> dict:
    """Build a fresh BaseNetwork, install ring TCP flows, and return stats."""
    net = Toolbox.BaseNetwork(
        name=f"ns3_tcp_circle_{flow_size_bytes}_{s.label}",
        backend="ns3",
        nb_node=NB_NODE,
        nb_link=NB_LINK,
        time_slice_duration_us=TIME_SLICE_US,
        guardband_us=2,
        ocs_tor_link_bw_gbps=OCS_TOR_LINK_BW_GBPS,
        tor_host_link_bw_gbps=TOR_HOST_LINK_BW_GBPS,
        admission_control=(s.routing_mode == "Per-hop"),
        use_webserver=False,
        simulation_stop_s=SIMULATION_STOP_S,
    )
    try:
        assert net.deploy_topo(s.topo())
        paths = s.routing(net)
        assert net.deploy_routing(paths, routing_mode=s.routing_mode)

        tcp_gen = net.tcp_traffic()
        for src, dst in RING_PAIRS:
            tcp_gen.bulk(
                src=src,
                dst=dst,
                size_bytes=flow_size_bytes,
                chunk_size_bytes=TCP_CHUNK_SIZE_BYTES,
                start_s=TCP_START_S,
                stop_s=TCP_STOP_S,
                name=f"h{src}-h{dst}-{flow_size_bytes}",
            )
        installed = tcp_gen.install()
        net.start()

        out = _empty_result()
        for inst in installed:
            stats = inst.stats()
            if stats is None:
                continue
            out["flow_size_bytes"].append(flow_size_bytes)
            out["src"].append(inst.spec.src)
            out["dst"].append(inst.spec.dst)
            out["tx_packets"].append(stats.tx_packets)
            out["rx_packets"].append(stats.rx_packets)
            out["lost_packets"].append(stats.lost_packets)
            out["tx_bytes"].append(stats.tx_bytes)
            out["rx_bytes"].append(stats.rx_bytes)
            out["throughput_mbps"].append(stats.throughput_bps / 1e6)
            out["delay_avg_ms"].append(stats.delay_avg_s * 1e3)
            out["delay_max_ms"].append(stats.delay_max_s * 1e3)
            out["fct_ms"].append(stats.fct_s * 1e3)
        return out
    finally:
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


def _empty_result() -> dict:
    return {
        "flow_size_bytes": [],
        "src": [],
        "dst": [],
        "tx_packets": [],
        "rx_packets": [],
        "lost_packets": [],
        "tx_bytes": [],
        "rx_bytes": [],
        "throughput_mbps": [],
        "delay_avg_ms": [],
        "delay_max_ms": [],
        "fct_ms": [],
    }


def _append_result(dst: dict, src: dict) -> None:
    for key, values in src.items():
        dst[key].extend(values)


def _finite(values: Iterable[float]) -> List[float]:
    return [v for v in values if math.isfinite(v)]


def _mean(values: Iterable[float]) -> float:
    vals = _finite(values)
    return statistics.fmean(vals) if vals else float("nan")


def _format_size(size_bytes: int) -> str:
    if size_bytes >= 1_000_000:
        return f"{size_bytes / 1_000_000:g} MB"
    return f"{size_bytes / 1_000:g} KB"


def _format_label(label: str) -> str:
    return (
        label.replace("opera + ", "Opera / ")
        .replace("routing_", "")
        .replace("(perhop)", "(per-hop)")
        .replace("(src)", "(source)")
    )


def _summary_rows(results: Dict[str, dict]) -> List[dict]:
    rows: List[dict] = []
    for label, data in results.items():
        for size in FLOW_SIZE_BYTES:
            indices = [
                i for i, value in enumerate(data["flow_size_bytes"])
                if value == size
            ]
            fct_values = [data["fct_ms"][i] for i in indices]
            tput_values = [data["throughput_mbps"][i] for i in indices]
            rx_bytes = sum(data["rx_bytes"][i] for i in indices)
            lost_packets = sum(data["lost_packets"][i] for i in indices)
            rows.append({
                "arch": label,
                "flow_size_bytes": size,
                "flow_size_label": _format_size(size),
                "flows": len(indices),
                "avg_fct_ms": _mean(fct_values),
                "avg_throughput_mbps": _mean(tput_values),
                "rx_bytes": rx_bytes,
                "lost_packets": lost_packets,
            })
    return rows


def _print_summary(rows: List[dict]) -> None:
    print()
    print(
        f"  {'Architecture':<34}{'size':>10}{'flows':>7}"
        f"{'avg FCT':>11}{'avg Mbps':>12}{'rx MB':>10}{'lost':>8}"
    )
    print("  " + "-" * 92)
    for row in rows:
        print(
            f"  {row['arch']:<34}{row['flow_size_label']:>10}"
            f"{row['flows']:>7}{row['avg_fct_ms']:>11.3f}"
            f"{row['avg_throughput_mbps']:>12.3f}"
            f"{row['rx_bytes'] / 1e6:>10.3f}{row['lost_packets']:>8}"
        )
    print()


def _write_raw_csv(path: str, results: Dict[str, dict]) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "arch", "flow_size_bytes", "src", "dst", "tx_packets",
            "rx_packets", "lost_packets", "tx_bytes", "rx_bytes",
            "throughput_mbps", "delay_avg_ms", "delay_max_ms", "fct_ms",
        ])
        for label, data in results.items():
            for row in zip(
                data["flow_size_bytes"], data["src"], data["dst"],
                data["tx_packets"], data["rx_packets"], data["lost_packets"],
                data["tx_bytes"], data["rx_bytes"], data["throughput_mbps"],
                data["delay_avg_ms"], data["delay_max_ms"], data["fct_ms"],
            ):
                (
                    size, src, dst, txp, rxp, lost, txb, rxb, tput, d_avg,
                    d_max, fct,
                ) = row
                w.writerow([
                    label, size, src, dst, txp, rxp, lost, txb, rxb,
                    f"{tput:.6f}", f"{d_avg:.6f}", f"{d_max:.6f}",
                    f"{fct:.6f}",
                ])


def _write_summary_csv(path: str, rows: List[dict]) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "arch", "flow_size_bytes", "flow_size_label", "flows",
            "avg_fct_ms", "avg_throughput_mbps", "rx_bytes", "lost_packets",
        ])
        for row in rows:
            w.writerow([
                row["arch"],
                row["flow_size_bytes"],
                row["flow_size_label"],
                row["flows"],
                f"{row['avg_fct_ms']:.6f}",
                f"{row['avg_throughput_mbps']:.6f}",
                row["rx_bytes"],
                row["lost_packets"],
            ])


def _write_json(path: str, results: Dict[str, dict]) -> None:
    out = {
        "meta": {
            "nb_node": NB_NODE,
            "nb_link": NB_LINK,
            "ring_pairs": RING_PAIRS,
            "flow_size_bytes": FLOW_SIZE_BYTES,
            "time_slice_duration_us": TIME_SLICE_US,
            "simulation_stop_s": SIMULATION_STOP_S,
            "tcp_start_s": TCP_START_S,
            "tcp_stop_s": TCP_STOP_S,
            "tcp_chunk_size_bytes": TCP_CHUNK_SIZE_BYTES,
            "ocs_tor_link_bw_gbps": OCS_TOR_LINK_BW_GBPS,
            "tor_host_link_bw_gbps": TOR_HOST_LINK_BW_GBPS,
        },
        "architectures": results,
    }
    with open(path, "w") as f:
        json.dump(out, f, indent=2)


def _apply_plot_style(plt) -> None:
    plt.rcParams.update({
        "figure.figsize": (6.8, 4.2),
        "figure.dpi": 150,
        "savefig.dpi": 300,
        "font.family": "serif",
        "font.serif": ["DejaVu Serif", "Times New Roman", "Times"],
        "font.size": 10,
        "axes.labelsize": 10,
        "axes.linewidth": 0.9,
        "legend.fontsize": 8.5,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "lines.linewidth": 2.5,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    })


def plot_fct_by_size(
    rows: List[dict],
    output_path: str = FCT_PLOT_PATH,
) -> Optional[Path]:
    """Draw flow size versus average FCT across architectures."""
    try:
        import matplotlib
        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
    except ImportError:
        print(
            "matplotlib is not installed; skipped FCT plot. "
            f"Summary data is in {SUMMARY_CSV_PATH}.",
            file=sys.stderr,
        )
        return None

    _apply_plot_style(plt)
    fig, ax = plt.subplots()
    for idx, scenario in enumerate(SCENARIOS):
        points = [
            row for row in rows
            if row["arch"] == scenario.label and row["flows"] > 0
        ]
        if not points:
            continue
        xs = [row["flow_size_bytes"] / 1e6 for row in points]
        ys = [row["avg_fct_ms"] for row in points]
        ax.plot(
            xs,
            ys,
            marker=_MARKERS[idx % len(_MARKERS)],
            markersize=5.0,
            color=_COLORS[idx % len(_COLORS)],
            label=_format_label(scenario.label),
        )

    try:
        ax.set_xscale("log", base=2)
    except TypeError:
        ax.set_xscale("log", basex=2)
    ax.set_xticks([size / 1e6 for size in FLOW_SIZE_BYTES])
    ax.set_xticklabels([_format_size(size) for size in FLOW_SIZE_BYTES])
    ax.set_xlabel("Flow size")
    ax.set_ylabel("Average FCT (ms)")
    ax.grid(True, which="major", linestyle="--", linewidth=0.6, alpha=0.35)
    ax.tick_params(axis="both", direction="in", length=4, width=0.8)
    ax.legend(loc="best", frameon=True, framealpha=0.95, edgecolor="0.8")

    fig.tight_layout()
    output = Path(output_path)
    fig.savefig(str(output), bbox_inches="tight")
    plt.close(fig)
    return output


# ----------------------------------------------------------------------- driver

def _run_single_to_file(scenario_index: int, flow_size_bytes: int, path: str) -> int:
    data = run_scenario(SCENARIOS[scenario_index], flow_size_bytes)
    with open(path, "w") as f:
        json.dump(data, f)
    return 0


def _run_child(scenario_index: int, flow_size_bytes: int) -> dict:
    fd, tmp_path = tempfile.mkstemp(
        prefix="openoptics_tcp_circle_",
        suffix=".json",
    )
    os.close(fd)
    try:
        cmd = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--single",
            "--scenario-index", str(scenario_index),
            "--flow-size", str(flow_size_bytes),
            "--single-output", tmp_path,
        ]
        completed = subprocess.run(
            cmd,
            cwd=str(Path.cwd()),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if completed.returncode != 0:
            if completed.stdout:
                print(completed.stdout, end="")
            raise RuntimeError(
                f"child simulation exited with code {completed.returncode}"
            )
        with open(tmp_path) as f:
            return json.load(f)
    finally:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass


def _run_sweep() -> int:
    results = {scenario.label: _empty_result() for scenario in SCENARIOS}
    for size in FLOW_SIZE_BYTES:
        for scenario_index, scenario in enumerate(SCENARIOS):
            print(
                f"[tcp-circle] running {scenario.label}, "
                f"flow_size={_format_size(size)} ...",
                flush=True,
            )
            try:
                data = _run_child(scenario_index, size)
                _append_result(results[scenario.label], data)
            except Exception as exc:
                print(f"[tcp-circle]   failed: {exc}", flush=True)

    summary_rows = _summary_rows(results)
    _print_summary(summary_rows)
    _write_raw_csv(RAW_CSV_PATH, results)
    _write_json(RAW_JSON_PATH, results)
    _write_summary_csv(SUMMARY_CSV_PATH, summary_rows)
    plot_path = plot_fct_by_size(summary_rows)

    print(f"  wrote {RAW_CSV_PATH}  (one row per TCP ring flow)")
    print(f"  wrote {RAW_JSON_PATH} (per-architecture arrays)")
    print(f"  wrote {SUMMARY_CSV_PATH} (average FCT by architecture/size)")
    if plot_path is not None:
        print(f"  wrote {plot_path} (flow size vs average FCT)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--single", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--scenario-index", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--flow-size", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--single-output", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.single:
        if args.scenario_index is None or args.flow_size is None:
            parser.error("--single requires --scenario-index and --flow-size")
        if args.single_output is None:
            parser.error("--single requires --single-output")
        return _run_single_to_file(
            scenario_index=args.scenario_index,
            flow_size_bytes=args.flow_size,
            path=args.single_output,
        )
    return _run_sweep()


if __name__ == "__main__":
    sys.exit(main())
