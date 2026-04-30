"""Plot per-architecture delay CDFs from rtt_comparison.json / .csv.

Intended to be run after ``examples/ns3_rtt_comparison.py`` has dumped
its artifacts. Each point on a CDF is one directed host pair's
FlowMonitor ``delay_avg_ms`` (one-way average delay). Uses matplotlib if
available; prints a clear install hint otherwise (so a CI that doesn't
have matplotlib doesn't fail).

Usage:
    python3 examples/plot_ns3_rtt_cdf.py                # writes rtt_cdfs.pdf
    python3 examples/plot_ns3_rtt_cdf.py --show         # interactive
    python3 examples/plot_ns3_rtt_cdf.py --logx         # log-scale x (tail detail)
    python3 examples/plot_ns3_rtt_cdf.py --input FILE   # explicit input path
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional


_VALUE_COLUMN = "delay_avg_ms"
DEFAULT_OUTPUT_PATH = "rtt_cdfs.pdf"

_COLORS = (
    "#0072B2",  # blue
    "#D55E00",  # vermillion
    "#009E73",  # green
    "#CC79A7",  # reddish purple
    "#E69F00",  # orange
    "#56B4E9",  # sky blue
    "#000000",  # black
)
_LINESTYLES = ("-", "--", "-.", ":")


def _load_json(path: Path) -> Dict[str, List[float]]:
    with path.open() as f:
        doc = json.load(f)
    archs = doc.get("architectures", {})
    return {
        label: list(data.get(_VALUE_COLUMN, []))
        for label, data in archs.items()
    }


def _load_csv(path: Path) -> Dict[str, List[float]]:
    out: Dict[str, List[float]] = defaultdict(list)
    with path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                out[row["arch"]].append(float(row[_VALUE_COLUMN]))
            except (KeyError, ValueError):
                continue
    return dict(out)


def _load(input_arg: Optional[str]) -> Dict[str, List[float]]:
    """Prefer the wide JSON if it exists; fall back to the long CSV."""
    if input_arg:
        p = Path(input_arg)
        if p.suffix == ".json":
            return _load_json(p)
        return _load_csv(p)
    for candidate in (Path("rtt_comparison.json"), Path("rtt_comparison.csv")):
        if candidate.exists():
            return _load_json(candidate) if candidate.suffix == ".json" else _load_csv(candidate)
    raise FileNotFoundError(
        "No rtt_comparison.json or rtt_comparison.csv in cwd. "
        "Run examples/ns3_rtt_comparison.py first, or pass --input."
    )


def _all_samples(data: Dict[str, List[float]]) -> Iterable[float]:
    for samples in data.values():
        for value in samples:
            yield value


def _apply_paper_style(plt) -> None:
    plt.rcParams.update({
        "figure.figsize": (6.8, 4.2),
        "figure.dpi": 150,
        "savefig.dpi": 300,
        "font.family": "serif",
        "font.serif": ["DejaVu Serif", "Times New Roman", "Times"],
        "font.size": 10,
        "axes.labelsize": 10,
        "axes.titlesize": 10,
        "axes.linewidth": 0.9,
        "legend.fontsize": 8.5,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "lines.linewidth": 2.6,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    })


def _format_label(label: str) -> str:
    return (
        label.replace("opera + ", "Opera / ")
        .replace("routing_", "")
        .replace("(perhop)", "(per-hop)")
        .replace("(src)", "(source)")
    )


def plot_rtt_cdf(
    input_path: Optional[str] = None,
    output_path: str = DEFAULT_OUTPUT_PATH,
    show: bool = False,
    logx: bool = False,
) -> Optional[Path]:
    """Render the RTT/delay CDF plot and return the output path.

    Returns ``None`` if matplotlib is unavailable, matching the example's
    previous non-fatal behavior.
    """
    try:
        import matplotlib
        if not show:
            matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib is not installed.\n"
              "Install it with: pip install matplotlib\n"
              "(Raw samples are already in rtt_comparison.csv / .json so you "
              "can plot with any external tool.)", file=sys.stderr)
        return None

    _apply_paper_style(plt)
    data = _load(input_path)

    if not data:
        raise ValueError("Loaded file contained no architectures.")

    fig, ax = plt.subplots()
    for idx, (label, samples) in enumerate(data.items()):
        if not samples:
            continue
        xs = sorted(samples)
        n = len(xs)
        ys = [(i + 1) / n for i in range(n)]
        ax.step(
            xs,
            ys,
            where="post",
            label=_format_label(label),
            color=_COLORS[idx % len(_COLORS)],
            linestyle=_LINESTYLES[(idx // len(_COLORS)) % len(_LINESTYLES)],
            linewidth=2.6,
        )

    samples = list(_all_samples(data))
    if not samples:
        raise ValueError("Loaded file contained no delay samples.")

    ax.set_xlabel("Per-flow average one-way delay (ms)")
    ax.set_ylabel("CDF")
    if logx:
        ax.set_xscale("log")
    ax.set_ylim(0.0, 1.01)
    x_min = min(samples)
    x_max = max(samples)
    if x_min < x_max:
        pad = 0.03 * (x_max - x_min)
        left = max(0.0, x_min - pad)
        if logx and left <= 0.0:
            positive_samples = [v for v in samples if v > 0.0]
            if not positive_samples:
                raise ValueError("Log-scale x-axis requires positive delay samples.")
            left = min(positive_samples)
        ax.set_xlim(left=left, right=x_max + pad)

    ax.grid(True, which="major", linestyle="--", linewidth=0.6, alpha=0.35)
    if logx:
        ax.grid(True, which="minor", linestyle=":", linewidth=0.4, alpha=0.2)
    ax.tick_params(axis="both", direction="in", length=4, width=0.8)
    ax.legend(loc="lower right", frameon=True, framealpha=0.95, edgecolor="0.8")

    fig.tight_layout()
    output = Path(output_path)
    fig.savefig(str(output), bbox_inches="tight")
    if show:
        plt.show()
    plt.close(fig)
    return output


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", help="Path to rtt_comparison.json or .csv")
    ap.add_argument("--output", default=DEFAULT_OUTPUT_PATH,
                    help=f"Output plot path (default: {DEFAULT_OUTPUT_PATH})")
    ap.add_argument("--show", action="store_true", help="Open an interactive window")
    ap.add_argument("--logx", action="store_true", help="Use log-scale x-axis")
    args = ap.parse_args()

    try:
        output = plot_rtt_cdf(
            input_path=args.input,
            output_path=args.output,
            show=args.show,
            logx=args.logx,
        )
    except (FileNotFoundError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 2

    if output is not None:
        print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
