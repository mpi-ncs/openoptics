# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# Author: Yiming Lei (ylei@mpi-inf.mpg.de)
#
# License text: Creative Commons NC BY SA 4.0
# https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en

"""ns-3 backend.

Drives a local ns-3 simulation via its Python bindings. The OpenOptics
contrib module under ``src/`` is linked in at ``openoptics-install-ns3``
time; this file builds the ns-3 topology, dispatches OpenOptics
``TableEntry`` objects to C++ calls on :class:`ns3::openoptics::OcsApp`
and :class:`TorApp`, and runs the simulator.

ns-3 is imported lazily inside :meth:`setup` so ``create_backend("ns3")``
can raise a clear ``RuntimeError`` when ``NS3_DIR`` / the bindings aren't
set up — instead of an ``ImportError`` at module load.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import warnings
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from openoptics.backends.base import (
    BackendBase,
    SwitchHandle,
    TableEntry,
    warn_if_overhead_exhausts_slice,
)
from openoptics.backends.ns3.install import env_config_path
from openoptics.backends.ns3.traffic import (
    FlowStats,
    TcpBulkFlowSpec,
    TcpTrafficGenerator,
    UdpFlowSpec,
    UdpTrafficGenerator,
)


def _resolve_ns3_dir() -> Optional[str]:
    """Return the path to a built ns-3 tree, or ``None``.

    Checks ``$NS3_DIR`` first, then the path recorded by
    ``openoptics-install-ns3`` in ``$OPENOPTICS_STATE_DIR/ns3_env.json``
    (default ``~/.openoptics/ns3_env.json``).
    """
    env = os.environ.get("NS3_DIR")
    if env:
        return env
    config = env_config_path()
    if not config.is_file():
        return None
    try:
        data = json.loads(config.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    val = data.get("ns3_dir")
    return str(val) if val else None


# Benign LLVM/cling noise emitted on first cppyy ns-3 import: a handful of
# static initializers in cling's in-memory module aren't JIT-resolvable.
# Simulation runs fine; we filter the lines so examples stay clean.
_BENIGN_NS3_STDERR_PATTERNS = (
    "runStaticInitializersOnce",
)


def _import_ns_quietly():
    """Import the `ns` module, filtering known-benign cling noise on fd 2.

    cling writes directly to fd 2, bypassing ``sys.stderr``, so
    ``contextlib.redirect_stderr`` alone doesn't catch it. Dup the fd to a
    temp file, run the import, then replay non-benign lines.
    """
    original_stderr_fd = os.dup(2)
    with tempfile.TemporaryFile(mode="w+b") as tmp:
        os.dup2(tmp.fileno(), 2)
        try:
            from ns import ns  # type: ignore[import-not-found]
        finally:
            os.dup2(original_stderr_fd, 2)
            os.close(original_stderr_fd)
            tmp.seek(0)
            captured = tmp.read().decode(errors="replace")
        for line in captured.splitlines(keepends=True):
            if not any(p in line for p in _BENIGN_NS3_STDERR_PATTERNS):
                sys.stderr.write(line)
    return ns


# Tables installed by ``setup_nodes()`` that this backend doesn't
# materialize — accepted silently so deploy_routing keeps flowing.
_IGNORED_TABLES = {
    "verify_desired_node",
}


def ocs_port_index(tor_id: int, link_id: int, nb_node: int) -> int:
    """Flat OCS port index for (tor_id, link_id).

    Matches Toolbox's port-major encoding ``port_id * nb_node + node_id``
    (see :meth:`BaseNetwork.cal_node_port_to_ocs_port`).
    """
    return link_id * nb_node + tor_id


class Ns3Backend(BackendBase):
    """ns-3 simulation backend.

    Supports OCS, ToR with per-hop or source routing, calendar queue
    (TIME_BASED only — traffic-aware/CONTROL_BASED not yet wired),
    UDP/TCP traffic generation, RTT probes, and the dashboard.
    """

    supports_device_manager = False
    supports_dashboard_without_device_manager = True
    supports_cli = False
    # Mirrors ``OpenOpticsSourceRouteHeader::kMaxHops``; exceeding it
    # ``NS_FATAL_ERROR``s on serialize/deserialize.
    max_source_route_hops = 16

    @classmethod
    def accepted_kwargs(cls) -> set:
        return {
            "link_delay_us",           # shorthand default for host_link_delay_us + ocs_link_delay_us
            "host_link_delay_us",      # propagation delay on host<->ToR p2p links
            "ocs_link_delay_us",       # propagation delay on ToR<->OCS p2p links
            "cq_buffer_bytes",         # total byte buffer limit per ToR calendar queue
            "simulation_stop_s",       # max simulated seconds before run() returns
            "snapshot_interval_us",    # dashboard sampling cadence (default = time_slice_duration_us)
            "verify_sr_cur_node",      # opt-in P4-style verify_desired_node for source-routed hops
            "admission_control",       # per-hop ADM: walk (dst, arrival_ts+offset) until AdmCheck passes; no-op for source routing (warns)
        }

    def __init__(self) -> None:
        self._ns3_dir = _resolve_ns3_dir()
        if not self._ns3_dir:
            raise RuntimeError(
                "ns-3 backend requires a built ns-3 source tree. Run "
                "`openoptics-install-ns3` to build one — that records "
                "the path under $OPENOPTICS_STATE_DIR (default "
                "~/.openoptics/ns3_env.json) so subsequent runs pick it "
                "up automatically. To override, set NS3_DIR (and "
                "PYTHONPATH) as printed by the helper."
            )
        # Make the cppyy-generated bindings importable without requiring the
        # caller to export PYTHONPATH manually.
        bindings = str(Path(self._ns3_dir) / "build" / "bindings" / "python")
        if bindings not in sys.path:
            sys.path.insert(0, bindings)
        # Mirror into the env so cppyy's lock-file lookup
        # (``<NS3_DIR>/.lock-ns3_*_build``) sees the same path.
        os.environ.setdefault("NS3_DIR", self._ns3_dir)
        self._src_dir = Path(__file__).resolve().parent / "src"

        # Populated in setup()
        self._ns = None                               # the `ns` cppyy module
        self._nb_node: int = 0
        self._nb_link: int = 0
        self._nb_time_slices: int = 0
        self._slice_duration_us: int = 0
        self._snapshot_interval_us: int = 0
        self._cq_buffer_bytes: int = 1_048_576
        self._simulation_stop_s: float = 2.0
        self._last_sim_time_s: float = 0.0
        self._host_link_delay_us: int = 1
        self._ocs_link_delay_us: int = 1
        self._guardband_us: int = 0

        # ns-3 simulation objects. All cppyy Ptrs; keep references alive.
        self._host_nodes: list = []
        self._tor_nodes: list = []
        self._ocs_node = None
        self._ocs_app = None                          # openoptics::OcsApp
        self._tor_apps: Dict[int, object] = {}        # tor_id -> openoptics::TorApp
        self._host_iface_addrs: List[str] = []        # "10.0.{i}.1" per host
        self._ip_to_tor: Dict[str, int] = {}

        # SwitchHandles — plain Python objects with the name + dummy thrift port.
        self._switch_handles: Dict[str, SwitchHandle] = {}

        # Dashboard wiring — populated in setup_dashboard() if use_webserver.
        self._sink = None                             # Ns3MetricSink instance
        self._dashboard_attached: bool = False
        self._ocs_listener = None                     # strong ref for cppyy
        self._tor_listeners: Dict[int, object] = {}   # strong refs per tor

        # FlowMonitor (installed in setup() on all IP nodes; consumed by
        # print_report() to compute end-to-end packet counts + delay stats).
        self._flow_helper = None
        self._flow_monitor = None
        # Snapshot of (flow_id, FlowStats) captured at the end of run() while
        # ns-3 state is still alive — so callers (e.g. ``InstalledTraffic
        # .stats()``) can read flow data after BaseNetwork.start() has torn
        # the simulator down. ``_flow_stats_index`` is a parallel dict keyed
        # by ``(src_ip, dst_ip, dst_port, protocol)`` for O(1) lookup from
        # ``flow_stats_for(spec)``; without it, examples that install tens of
        # thousands of flows degenerate to O(N²) post-run iteration.
        self._flow_stats_records: List[Tuple[int, "FlowStats"]] = []
        self._flow_stats_index: Dict[Tuple[str, str, int, str], "FlowStats"] = {}

        # Traffic-gen apps pinned for lifetime of the run.
        self._traffic_apps: list = []
        self._next_traffic_port: int = 9000

    # ------------------------------------------------------------------
    # BackendBase interface
    # ------------------------------------------------------------------

    def setup(
        self,
        *,
        nb_node: int,
        nb_host_per_tor: int,
        nb_link: int,
        nb_time_slices: int,
        time_slice_duration_us: int,
        guardband_us: int,
        calendar_queue_mode: int,
        ocs_tor_link_bw_gbps: float = 1.0,
        tor_host_link_bw_gbps: float = 1.0,
        **backend_kwargs,
    ) -> None:
        if nb_host_per_tor != 1:
            raise NotImplementedError(
                "Ns3Backend currently supports exactly one host per ToR; "
                f"got nb_host_per_tor={nb_host_per_tor}"
            )
        if calendar_queue_mode != 0:
            raise NotImplementedError(
                "Ns3Backend currently supports only TIME_BASED calendar "
                "queues (calendar_queue_mode=0); CONTROL_BASED is not yet "
                "wired."
            )

        self._nb_node = nb_node
        self._nb_link = nb_link
        self._nb_time_slices = max(nb_time_slices, 1)
        self._slice_duration_us = int(time_slice_duration_us)
        cq_buffer_bytes = backend_kwargs.get("cq_buffer_bytes", 1_048_576)
        if not isinstance(cq_buffer_bytes, int) or isinstance(cq_buffer_bytes, bool):
            raise ValueError("cq_buffer_bytes must be a positive integer")
        if cq_buffer_bytes <= 0:
            raise ValueError("cq_buffer_bytes must be a positive integer")
        self._cq_buffer_bytes = cq_buffer_bytes
        self._simulation_stop_s = float(
            backend_kwargs.get("simulation_stop_s", 2.0)
        )
        # Default dashboard sampling cadence is one snapshot per slice. Users
        # can override for sub-slice fidelity or coarser stress-run sampling.
        self._snapshot_interval_us = int(
            backend_kwargs.get("snapshot_interval_us", time_slice_duration_us)
        )

        # Propagation delay: `link_delay_us` is the shorthand default for
        # both host<->tor and tor<->ocs links. Explicit per-link kwargs win.
        link_delay_us = int(backend_kwargs.get("link_delay_us", 1))
        self._host_link_delay_us = int(
            backend_kwargs.get("host_link_delay_us", link_delay_us)
        )
        self._ocs_link_delay_us = int(
            backend_kwargs.get("ocs_link_delay_us", link_delay_us)
        )
        self._guardband_us = int(guardband_us)
        warn_if_overhead_exhausts_slice(
            guardband_us=self._guardband_us,
            slice_duration_us=self._slice_duration_us,
            link_delay_us=self._ocs_link_delay_us,
            backend_name="ns3",
        )

        # Opt-in P4-style `verify_desired_node` for source-routed hops.
        self._verify_sr_cur_node = bool(
            backend_kwargs.get("verify_sr_cur_node", False)
        )

        # Per-hop admission control: when on, the ToR walks
        # ``(dst, arrival_ts + offset)`` until AdmCheck passes (drops to
        # ``m_dropAdmFail`` if none does). Per-hop only — see
        # ``_apply_entry`` for the SR-mode warning.
        self._admission_control = bool(
            backend_kwargs.get("admission_control", False)
        )
        self._sr_adm_warned = False

        # Lazy import. cling's benign static-initializer noise is filtered
        # by _import_ns_quietly.
        try:
            ns = _import_ns_quietly()
        except Exception as e:  # pragma: no cover — environmental
            raise RuntimeError(
                "Failed to import ns-3 Python bindings. Verify that "
                "NS3_DIR and PYTHONPATH are set as printed by "
                "`openoptics-install-ns3`. Original error: " + repr(e)
            )
        self._ns = ns

        self._build_topology(
            nb_node=nb_node,
            nb_link=nb_link,
            # ns-3's PointToPoint DataRate attribute and our TorApp
            # byte-budget accounting both consume Mbps; convert once here.
            ocs_tor_link_bw_mbps=int(round(ocs_tor_link_bw_gbps * 1000)),
            tor_host_link_bw_mbps=int(round(tor_host_link_bw_gbps * 1000)),
            host_link_delay_us=self._host_link_delay_us,
            ocs_link_delay_us=self._ocs_link_delay_us,
        )

        # Register switch handles. thrift_port is a dummy (0) since ns-3
        # has no Thrift plane; callers that grab the handle only use .name.
        self._switch_handles["ocs"] = SwitchHandle("ocs", 0)
        for tor_id in range(nb_node):
            self._switch_handles[f"tor{tor_id}"] = SwitchHandle(f"tor{tor_id}", 0)

    def get_switch(self, name: str) -> SwitchHandle:
        return self._switch_handles[name]

    def switch_exists(self, name: str) -> bool:
        return name in self._switch_handles

    def get_tor_switches(self) -> list:
        return [self._switch_handles[f"tor{i}"] for i in range(self._nb_node)]

    def get_optical_switches(self) -> list:
        return [self._switch_handles["ocs"]] if "ocs" in self._switch_handles else []

    def get_ip_to_tor(self) -> dict:
        return dict(self._ip_to_tor)

    def load_table(
        self,
        switch_name: str,
        entries: list,
        print_flag: bool = False,
        save_flag: bool = False,
        save_name: str = "saved_commands",
    ) -> bool:
        for entry in entries:
            if entry.is_default_action:
                # OpenOptics' only default action is ocs_schedule.drop;
                # OcsApp already drops on missing schedule entries, so
                # there's nothing to install here.
                continue
            self._apply_entry(switch_name, entry)
        return True

    def clear_table(
        self,
        switch_name: str,
        table: str,
        print_flag: bool = False,
    ) -> None:
        if switch_name == "ocs" and table == "ocs_schedule":
            self._ocs_app.ClearSchedule()
            return
        if switch_name.startswith("tor"):
            tor_id = int(switch_name[3:])
            app = self._tor_apps[tor_id]
            if table == "per_hop_routing":
                app.ClearPerHop()
            elif table == "ip_to_dst_node":
                app.ClearIpToDst()
            elif table == "arrive_at_dst":
                app.ClearArriveAtDst()
            elif table == "add_source_routing_entries":
                app.ClearSourceRouting()
            elif table == "cal_port_slice_to_node":
                app.ClearCalPortSliceToNode()
            # Other tables (e.g. verify_desired_node) aren't materialized.
            return
        # Unknown switch_name — silently accept; raising would break
        # deploy_routing for tables we don't handle.

    def stop(self) -> None:
        """Tear down the simulator and reset process-wide ns-3 state.

        ``Ipv4AddressGenerator.Reset()`` is what makes this re-runnable:
        without it, a subsequent ``BaseNetwork`` in the same process
        ``NS_FATAL``s on ``10.0.{tor_id}.0/24`` collisions. Application
        ``Ptr<>``s held by Python (e.g. RTT probes) survive ``Destroy``
        and stay readable. Idempotent.
        """
        if self._ns is None:
            return
        ns = self._ns
        ns.Simulator.Stop()
        ns.Simulator.Destroy()
        ns.Ipv4AddressGenerator.Reset()
        self._ns = None

    def cleanup(self) -> None:
        """No-op; teardown is folded into :meth:`stop`."""

    def run(self) -> None:
        """Advance the simulator until ``simulation_stop_s``, print the
        report, and (if the dashboard is attached and stdin is a TTY) wait
        for Enter so the user can inspect the live charts.

        Set ``OPENOPTICS_NS3_NO_PAUSE=1`` to skip the wait under CI.
        """
        if self._ns is None:
            return
        self._ns.Simulator.Stop(self._ns.Seconds(self._simulation_stop_s))
        print(f"[ns3] Running simulation for {self._simulation_stop_s:.2f}s...")
        self._ns.Simulator.Run()
        self._last_sim_time_s = self._ns.Simulator.Now().GetSeconds()
        print("[ns3] Simulation finished.")

        # Snapshot FlowMonitor into pure Python before BaseNetwork.start()
        # invokes stop() (which calls Simulator.Destroy and clears self._ns).
        # Stats consumers like InstalledTraffic.stats() read from the
        # snapshot and don't need the simulator alive.
        self._flow_stats_records = self._snapshot_flow_stats()

        self.print_report()

        if self._dashboard_attached and self._should_pause_post_run():
            try:
                input("[ns3] Press Enter to stop the dashboard and exit... ")
            except EOFError:
                pass

    @staticmethod
    def _should_pause_post_run() -> bool:
        if os.environ.get("OPENOPTICS_NS3_NO_PAUSE"):
            return False
        return sys.stdin.isatty() and sys.stdout.isatty()

    def print_report(self) -> None:
        """Print a post-run summary: per-switch C++ counters,
        per-drop-site break-down, and per-flow FlowMonitor stats.
        Suppressed when ``OPENOPTICS_NS3_NO_REPORT=1``.
        """
        if self._ocs_app is None:
            return
        if os.environ.get("OPENOPTICS_NS3_NO_REPORT"):
            return

        sim_time_s = (
            self._ns.Simulator.Now().GetSeconds()
            if self._ns is not None
            else self._last_sim_time_s
        )

        def rule(char="=", width=72):
            print(char * width)

        print()
        rule("=")
        print(f"  OpenOptics ns-3 Simulation Report")
        rule("=")
        print(f"  Simulated time:          {sim_time_s:.3f} s")
        print(f"  Slice duration:          {self._slice_duration_us} us "
              f"({self._nb_time_slices} slices)")
        effective_us = max(
            0,
            self._slice_duration_us - self._guardband_us - self._ocs_link_delay_us,
        )
        print(
            f"  Guardband:               {self._guardband_us} us   "
            f"Host link delay: {self._host_link_delay_us} us   "
            f"OCS link delay: {self._ocs_link_delay_us} us"
        )
        print(
            f"  Effective active window: {effective_us} us/slice "
            f"(byte budget = slice - guardband - ocs_delay)"
        )
        if self._dashboard_attached:
            print(f"  Dashboard snapshot rate: every {self._snapshot_interval_us} us")

        # ---- Per-switch counters ----
        rule("-")
        print(f"  Per-switch counters")
        rule("-")
        hdr = (f"  {'switch':<8}{'from_host':>12}{'from_uplink':>13}"
               f"{'forwarded':>12}{'delivered':>12}{'drops':>8}{'ovfl_drops':>12}")
        print(hdr)

        ocs_fwd = int(self._ocs_app.GetForwardCount())
        ocs_drop = int(self._ocs_app.GetDropCount())
        print(f"  {'ocs':<8}{'-':>12}{'-':>13}"
              f"{ocs_fwd:>12}{'-':>12}{ocs_drop:>8}{'-':>12}")

        total_from_host = 0
        total_delivered = 0
        total_drops = ocs_drop
        total_ovfl = 0
        for tor_id in sorted(self._tor_apps):
            a = self._tor_apps[tor_id]
            from_host = int(a.GetIngressFromHostCount())
            from_uplink = int(a.GetIngressFromUplinkCount())
            fwd = int(a.GetForwardedCount())
            delivered = int(a.GetDeliveredToHostCount())
            drops = int(a.GetDropCount())
            ovfl = int(a.GetSliceOverflowDrops())
            total_from_host += from_host
            total_delivered += delivered
            total_drops += drops
            total_ovfl += ovfl
            print(f"  {f'tor{tor_id}':<8}{from_host:>12}{from_uplink:>13}"
                  f"{fwd:>12}{delivered:>12}{drops:>8}{ovfl:>12}")
        print(f"  {'total':<8}{total_from_host:>12}{'-':>13}"
              f"{'-':>12}{total_delivered:>12}{total_drops:>8}{total_ovfl:>12}")
        if total_ovfl:
            print(f"  (ovfl_drops = packets rejected by per-slice byte "
                  f"budget; indicates saturated uplinks)")

        # ---- Per-drop-site break-down (only non-zero, totalled) ----
        if total_drops:
            # Order matches openoptics-tor-app.cc; see GetDrop*() getters.
            site_getters = (
                ("FromHostNoIp",      "GetDropFromHostNoIp"),
                ("FromUplinkParse",   "GetDropFromUplinkParse"),
                ("FromUplinkProtocol","GetDropFromUplinkProtocol"),
                ("PerHopMissed",      "GetDropPerHopMissed"),
                ("PerHopSentinel",    "GetDropPerHopSentinel"),
                ("ForwardPort",       "GetDropForwardPort"),
                ("ForwardCq",         "GetDropForwardCq"),
                ("ForwardSendFail",   "GetDropForwardSendFail"),
                ("ResolveRandom",     "GetDropResolveRandom"),
                ("ResolveNode",       "GetDropResolveNode"),
                ("ResolveFallthrough","GetDropResolveFallthrough"),
                ("SrEmpty",           "GetDropSrEmpty"),
                ("SrIngressBadCur",   "GetDropSrIngressBadCur"),
                ("SrUplinkSize",      "GetDropSrUplinkSize"),
                ("SrEndNotDst",       "GetDropSrEndNotDst"),
                ("SrTransitBadCur",   "GetDropSrTransitBadCur"),
                ("AdmFail",           "GetDropAdmFail"),
            )
            site_totals = []
            for label, fn_name in site_getters:
                total = 0
                for tor_id in sorted(self._tor_apps):
                    total += int(getattr(self._tor_apps[tor_id], fn_name)())
                if total:
                    site_totals.append((label, total))
            if site_totals:
                site_totals.sort(key=lambda t: -t[1])
                print(f"  drop reasons (totalled across all ToRs):")
                for label, total in site_totals:
                    print(f"    {label:<22}{total:>10}")

        # ---- Flow-level end-to-end ----
        if not self._flow_stats_records:
            rule("=")
            print()
            return

        rule("-")
        print(f"  Per-flow end-to-end (FlowMonitor)")
        rule("-")

        # Per-flow detail is useful for small scenarios but turns into
        # thousands of lines once the example installs many flows. Cap
        # the per-flow print at OPENOPTICS_NS3_FLOW_DETAIL_MAX (default
        # 32); above that threshold print only the rolled-up totals.
        try:
            detail_max = int(os.environ.get("OPENOPTICS_NS3_FLOW_DETAIL_MAX", "32"))
        except ValueError:
            detail_max = 32
        verbose = len(self._flow_stats_records) <= detail_max

        n_flows = 0
        sum_tx = sum_rx = sum_lost = 0
        for flow_id, stats in self._flow_stats_records:
            n_flows += 1
            sum_tx += stats.tx_packets
            sum_rx += stats.rx_packets
            sum_lost += stats.lost_packets
            if not verbose:
                continue
            loss_pct = (stats.lost_packets / stats.tx_packets * 100.0) if stats.tx_packets else 0.0
            print(
                f"  Flow {flow_id}  "
                f"{stats.src_ip}:{stats.src_port} -> "
                f"{stats.dst_ip}:{stats.dst_port}  "
                f"{stats.protocol.upper()}"
            )
            print(
                f"    tx={stats.tx_packets}  rx={stats.rx_packets}  "
                f"lost={stats.lost_packets} ({loss_pct:.1f}%)  "
                f"tx_bytes={stats.tx_bytes}  rx_bytes={stats.rx_bytes}"
            )
            if stats.rx_packets > 0:
                jitter_str = (
                    f"jitter_avg={stats.jitter_avg_s * 1e3:.3f} ms"
                    if stats.rx_packets > 1
                    else "jitter_avg=n/a (<2 rx)"
                )
                tput_kbps = (
                    stats.throughput_bps / 1e3
                    if stats.rx_packets > 1
                    else 0.0
                )
                print(
                    f"    delay_avg={stats.delay_avg_s * 1e3:.3f} ms  "
                    f"delay_min={stats.delay_min_s * 1e3:.3f} ms  "
                    f"delay_max={stats.delay_max_s * 1e3:.3f} ms"
                )
                print(
                    f"    {jitter_str}  throughput={tput_kbps:.2f} Kb/s"
                )
            else:
                print(f"    (no received packets; nothing to time)")

        if not verbose:
            print(
                f"  ({n_flows} flows; per-flow detail suppressed — "
                f"raise OPENOPTICS_NS3_FLOW_DETAIL_MAX to see per-flow lines)"
            )

        if n_flows == 0:
            print("  (no flows observed — no traffic installed?)")
        else:
            overall_loss = (sum_lost / sum_tx * 100.0) if sum_tx else 0.0
            rule("-")
            print(
                f"  Totals:  tx={sum_tx}  rx={sum_rx}  lost={sum_lost} "
                f"({overall_loss:.1f}%)  flows={n_flows}"
            )
        rule("=")
        print()

    def setup_dashboard(self, service) -> None:
        """Wire each app's snapshot listener to an Ns3MetricSink so live
        telemetry flows into the dashboard.

        cppyy's ``MakeCallback`` doesn't accept Python callables; the
        ``SetSnapshotListener`` ``std::function`` setter does, since cppyy
        converts bound methods transparently. The ns-3-native ``"Snapshot"``
        trace source still fires alongside the listener.
        """
        # No-op if setup() never ran. Shouldn't happen via Toolbox, which
        # always calls setup_dashboard after deploy_topo has run setup().
        if self._ns is None or self._ocs_app is None:
            return

        from openoptics.dashboard.collectors import Ns3MetricSink

        sink = Ns3MetricSink()
        service.register_event_source(sink)    # binds repo/broker/epoch_id
        self._sink = sink

        ns = self._ns
        interval = ns.MicroSeconds(self._snapshot_interval_us)

        # Bound methods are freshly created on each attribute access and
        # cppyy's std::function holds no strong Python ref — pin them
        # ourselves or the C++ listener fires into a GC'd callable.
        self._ocs_listener = sink.on_ocs_snapshot
        self._tor_listeners = {
            tor_id: sink.on_tor_snapshot for tor_id in self._tor_apps
        }

        self._ocs_app.SetSnapshotListener(self._ocs_listener)
        self._ocs_app.ScheduleSnapshots(interval)

        for tor_id, app in self._tor_apps.items():
            app.SetSnapshotListener(self._tor_listeners[tor_id])
            app.ScheduleSnapshots(interval)

        self._dashboard_attached = True

    # ------------------------------------------------------------------
    # Traffic builders. User code normally reaches these via BaseNetwork's
    # net.udp_traffic() / net.tcp_traffic() facade.
    # ------------------------------------------------------------------

    def udp_traffic(self, **defaults) -> UdpTrafficGenerator:
        """Return a UDP traffic builder for this simulation.

        Use after ``deploy_routing()`` and before ``start()``::

            net.udp_traffic() \\
                .flow(0, 1, rate="10Mbps", duration_s=0.5) \\
                .install()

        The builder validates node ids, translates rates/durations into packet
        counts, assigns unique UDP ports, and then calls the concrete ns-3 app
        installers below.
        """
        return UdpTrafficGenerator(self, **defaults)

    def tcp_traffic(self, **defaults) -> TcpTrafficGenerator:
        """Return a TCP traffic builder for this simulation.

        Use after ``deploy_routing()`` and before ``start()``::

            net.tcp_traffic() \\
                .bulk(0, 1, size_bytes=10_000_000, duration_s=0.5) \\
                .install()
        """
        return TcpTrafficGenerator(self, **defaults)

    def _allocate_traffic_port(self) -> int:
        port = self._next_traffic_port
        self._next_traffic_port += 1
        return port

    def install_udp_flow(
        self,
        src: int,
        dst: int,
        *,
        start_s: float = 0.1,
        stop_s: float = 1.0,
        num_packets: int = 20,
        packet_size_bytes: int = 256,
        interval_s: float = 0.01,
        port: int = 9,
    ):
        """Install one-way UDP client/server traffic from ``h<src>`` to
        ``h<dst>``.

        This is the concrete installer used by :class:`UdpTrafficGenerator` for
        ``flow(...)``. For request/reply traffic, use ``udp_traffic().echo(...)``.
        """
        return self._install_udp_apps(
            src=src,
            dst=dst,
            start_s=start_s,
            stop_s=stop_s,
            num_packets=num_packets,
            packet_size_bytes=packet_size_bytes,
            interval_s=interval_s,
            port=port,
            echo=False,
        )

    def install_tcp_bulk_flow(
        self,
        src: int,
        dst: int,
        *,
        start_s: float = 0.1,
        stop_s: float = 1.0,
        max_bytes: int = 0,
        send_size_bytes: int = 1024,
        port: int = 9,
    ):
        """Install one TCP BulkSend flow from ``h<src>`` to ``h<dst>``.

        ``max_bytes`` maps to ns-3's ``BulkSendApplication.MaxBytes``. A
        value of 0 means unlimited until ``stop_s``.
        """
        ns = self._ns
        if ns is None:
            raise RuntimeError("traffic installer called before setup()")
        self._validate_traffic_endpoints(src, dst)
        if int(max_bytes) < 0:
            raise ValueError("max_bytes must be non-negative")
        if int(send_size_bytes) <= 0:
            raise ValueError("send_size_bytes must be positive")

        protocol = "ns3::TcpSocketFactory"
        sink = ns.PacketSinkHelper(
            protocol, self._traffic_bind_address(port)
        )
        sink_app = sink.Install(self._host_nodes[dst])
        sink_app.Start(ns.Seconds(0.0))
        sink_app.Stop(ns.Seconds(self._simulation_stop_s))

        source = ns.BulkSendHelper(
            protocol, self._traffic_remote_address(dst, port)
        )
        source.SetAttribute("MaxBytes", ns.UintegerValue(int(max_bytes)))
        source.SetAttribute(
            "SendSize", ns.UintegerValue(int(send_size_bytes))
        )
        source_app = source.Install(self._host_nodes[src])
        source_app.Start(ns.Seconds(start_s))
        source_app.Stop(ns.Seconds(stop_s))

        self._traffic_apps.extend([sink_app, source_app])
        return sink_app, source_app

    def install_onoff_flow(
        self,
        src: int,
        dst: int,
        *,
        protocol: str,
        start_s: float = 0.1,
        stop_s: float = 1.0,
        rate_bps: float = 1_000_000.0,
        max_bytes: int = 0,
        packet_size_bytes: int = 1024,
        port: int = 9,
    ):
        """Install a rate-shaped TCP or UDP OnOff flow."""
        ns = self._ns
        if ns is None:
            raise RuntimeError("traffic installer called before setup()")
        self._validate_traffic_endpoints(src, dst)
        if int(max_bytes) < 0:
            raise ValueError("max_bytes must be non-negative")
        if float(rate_bps) <= 0:
            raise ValueError("rate_bps must be positive")
        if int(packet_size_bytes) <= 0:
            raise ValueError("packet_size_bytes must be positive")

        protocol_name = str(protocol).strip().lower()
        if protocol_name == "tcp":
            factory = "ns3::TcpSocketFactory"
        elif protocol_name == "udp":
            factory = "ns3::UdpSocketFactory"
        else:
            raise ValueError("protocol must be 'tcp' or 'udp'")

        sink = ns.PacketSinkHelper(
            factory, self._traffic_bind_address(port)
        )
        sink_app = sink.Install(self._host_nodes[dst])
        sink_app.Start(ns.Seconds(0.0))
        sink_app.Stop(ns.Seconds(self._simulation_stop_s))

        source = ns.OnOffHelper(
            factory, self._traffic_remote_address(dst, port)
        )
        source.SetConstantRate(
            ns.DataRate(f"{int(round(rate_bps))}bps"),
            int(packet_size_bytes),
        )
        source.SetAttribute("MaxBytes", ns.UintegerValue(int(max_bytes)))
        source_app = source.Install(self._host_nodes[src])
        source_app.Start(ns.Seconds(start_s))
        source_app.Stop(ns.Seconds(stop_s))

        self._traffic_apps.extend([sink_app, source_app])
        return sink_app, source_app

    def install_udp_echo_flow(
        self,
        src: int,
        dst: int,
        *,
        start_s: float = 0.1,
        stop_s: float = 1.0,
        num_packets: int = 20,
        packet_size_bytes: int = 256,
        interval_s: float = 0.01,
        port: int = 9,
    ):
        """Install a UdpEchoClient on h<src> pointing at h<dst>, plus a
        UdpEchoServer on h<dst>.

        The client sends `num_packets` at `interval_s` spacing; the server
        echoes each one back. Both apps' counts are exposed via the app
        pointers stored in ``self._traffic_apps`` for test assertions.
        """
        return self._install_udp_apps(
            src=src,
            dst=dst,
            start_s=start_s,
            stop_s=stop_s,
            num_packets=num_packets,
            packet_size_bytes=packet_size_bytes,
            interval_s=interval_s,
            port=port,
            echo=True,
        )

    def _install_udp_apps(
        self,
        *,
        src: int,
        dst: int,
        start_s: float,
        stop_s: float,
        num_packets: int,
        packet_size_bytes: int,
        interval_s: float,
        port: int,
        echo: bool,
    ):
        ns = self._ns
        if ns is None:
            raise RuntimeError("traffic installer called before setup()")
        self._validate_traffic_endpoints(src, dst)

        server = (
            ns.UdpEchoServerHelper(port)
            if echo else ns.UdpServerHelper(port)
        )
        server_app = server.Install(self._host_nodes[dst])
        server_app.Start(ns.Seconds(0.0))
        server_app.Stop(ns.Seconds(self._simulation_stop_s))

        # cppyy doesn't follow ns-3's implicit Ipv4Address -> Address
        # conversion; construct an Address explicitly via InetSocketAddress.
        dst_addr = ns.InetSocketAddress(
            ns.Ipv4Address(self._host_iface_addrs[dst]), port
        ).ConvertTo()
        client = (
            ns.UdpEchoClientHelper(dst_addr)
            if echo else ns.UdpClientHelper(dst_addr)
        )
        client.SetAttribute("MaxPackets", ns.UintegerValue(num_packets))
        client.SetAttribute("Interval", ns.TimeValue(ns.Seconds(interval_s)))
        client.SetAttribute("PacketSize", ns.UintegerValue(packet_size_bytes))
        client_app = client.Install(self._host_nodes[src])
        client_app.Start(ns.Seconds(start_s))
        client_app.Stop(ns.Seconds(stop_s))

        self._traffic_apps.extend([server_app, client_app])
        return server_app, client_app

    def _validate_traffic_endpoints(self, src: int, dst: int) -> None:
        if not (0 <= src < self._nb_node and 0 <= dst < self._nb_node):
            raise IndexError(
                f"src={src} dst={dst} out of range 0..{self._nb_node - 1}"
            )

    def _traffic_remote_address(self, dst: int, port: int):
        ns = self._ns
        return ns.InetSocketAddress(
            ns.Ipv4Address(self._host_iface_addrs[dst]), int(port)
        ).ConvertTo()

    def _traffic_bind_address(self, port: int):
        ns = self._ns
        return ns.InetSocketAddress(
            ns.Ipv4Address.GetAny(), int(port)
        ).ConvertTo()

    # ------------------------------------------------------------------
    # Flow-level measurement (FlowMonitor)
    # ------------------------------------------------------------------

    def _snapshot_flow_stats(self) -> List[Tuple[int, FlowStats]]:
        """Snapshot FlowMonitor into pure Python via a single C++ XML dump.

        ns-3's ``FlowMonitor::SerializeToXmlString`` returns a string
        containing both the per-flow numerics (``<FlowStats>``) and the
        registered classifier 5-tuple table (``<Ipv4FlowClassifier>``) in
        one allocation. Going through XML costs us a single cppyy
        boundary crossing regardless of flow count; the alternative —
        iterating ``GetFlowStats()`` and reading 12+ attributes per flow
        plus ``FindFlow`` — was ``O(N)`` cppyy crossings, which dominated
        runtime once the user installed tens of thousands of flows.

        Called once at the end of :meth:`run` while the simulator is
        still alive. The returned records are pure Python, so they
        remain valid after ``BaseNetwork.start()`` tears the simulator
        down.

        Side effect: rebuilds ``self._flow_stats_index`` so
        :meth:`flow_stats_for` is O(1) regardless of flow count.
        """
        self._flow_stats_index = {}
        if self._flow_monitor is None or self._ns is None:
            return []
        self._flow_monitor.CheckForLostPackets()
        # No histograms, no per-probe stats — we only need flow numerics
        # + classifier 5-tuples. Indent 0 keeps the string compact.
        # cppyy returns ``std::string`` as a wrapper that ElementTree
        # rejects; force a Python str.
        xml_str = str(self._flow_monitor.SerializeToXmlString(0, False, False))
        return self._parse_flow_monitor_xml(xml_str)

    @staticmethod
    def _parse_ns3_time_seconds(text: str) -> float:
        """Convert an ns-3 ``Time::As(Time::NS)`` attribute (e.g.
        ``"+1234.0ns"``) to seconds."""
        s = text.strip()
        if s.endswith("ns"):
            return float(s[:-2]) / 1e9
        raise ValueError(f"unexpected ns-3 time format: {text!r}")

    def _parse_flow_monitor_xml(self, xml_str: str) -> List[Tuple[int, FlowStats]]:
        """Parse a FlowMonitor XML report into ``(flow_id, FlowStats)`` records.

        Two passes: first the ``<Ipv4FlowClassifier>`` block to map
        ``flow_id`` → 5-tuple, then the ``<FlowStats>`` block for
        numerics joined against that map. Any ``<Ipv6FlowClassifier>`` /
        other blocks are ignored. ``flow_id`` is only an internal join
        key; the public lookup index is keyed by the tuple
        ``(src_ip, dst_ip, dst_port, protocol)`` like before.
        """
        root = ET.fromstring(xml_str)

        five_tuple: Dict[int, Tuple[str, str, int, int, str]] = {}
        for cls in root.findall("Ipv4FlowClassifier"):
            for flow_xml in cls.findall("Flow"):
                flow_id = int(flow_xml.get("flowId"))
                proto_num = int(flow_xml.get("protocol"))
                five_tuple[flow_id] = (
                    flow_xml.get("sourceAddress", ""),
                    flow_xml.get("destinationAddress", ""),
                    int(flow_xml.get("sourcePort")),
                    int(flow_xml.get("destinationPort")),
                    {6: "tcp", 17: "udp"}.get(proto_num, str(proto_num)),
                )

        records: List[Tuple[int, FlowStats]] = []
        flow_stats_root = root.find("FlowStats")
        if flow_stats_root is None:
            return records
        parse_t = self._parse_ns3_time_seconds
        for flow_xml in flow_stats_root.findall("Flow"):
            flow_id = int(flow_xml.get("flowId"))
            rx = int(flow_xml.get("rxPackets"))
            tx = int(flow_xml.get("txPackets"))
            if rx > 0:
                t_first_tx = parse_t(flow_xml.get("timeFirstTxPacket"))
                t_last_rx = parse_t(flow_xml.get("timeLastRxPacket"))
                t_first_rx = parse_t(flow_xml.get("timeFirstRxPacket"))
                delay_avg = parse_t(flow_xml.get("delaySum")) / rx
                delay_min = parse_t(flow_xml.get("minDelay"))
                delay_max = parse_t(flow_xml.get("maxDelay"))
                fct_s = max(0.0, t_last_rx - t_first_tx)
            else:
                delay_avg = delay_min = delay_max = float("nan")
                fct_s = float("nan")
                t_first_rx = t_last_rx = float("nan")
            if rx > 1:
                jitter_avg = parse_t(flow_xml.get("jitterSum")) / (rx - 1)
                span = max(t_last_rx - t_first_rx, 1e-9)
                throughput_bps = int(flow_xml.get("rxBytes")) * 8.0 / span
            else:
                jitter_avg = float("nan")
                throughput_bps = float("nan")
            src_ip, dst_ip, src_port, dst_port, proto = five_tuple.get(
                flow_id, ("", "", 0, 0, "")
            )
            fs = FlowStats(
                src_ip=src_ip,
                dst_ip=dst_ip,
                src_port=src_port,
                dst_port=dst_port,
                protocol=proto,
                tx_packets=tx,
                rx_packets=rx,
                lost_packets=int(flow_xml.get("lostPackets")),
                tx_bytes=int(flow_xml.get("txBytes")),
                rx_bytes=int(flow_xml.get("rxBytes")),
                delay_avg_s=delay_avg,
                delay_min_s=delay_min,
                delay_max_s=delay_max,
                jitter_avg_s=jitter_avg,
                fct_s=fct_s,
                throughput_bps=throughput_bps,
            )
            records.append((flow_id, fs))
            if proto:
                self._flow_stats_index[(src_ip, dst_ip, dst_port, proto)] = fs
        return records

    def get_flow_stats(self) -> List[FlowStats]:
        """Return per-flow end-to-end stats from FlowMonitor.

        Valid after :meth:`run` (typically called via ``net.start()``).
        Reads from the snapshot captured at the end of ``run()`` so it
        keeps working after the simulator has been torn down. Returns an
        empty list if no flows were observed.
        """
        return [stats for _fid, stats in self._flow_stats_records]

    def flow_stats_for(self, spec) -> Optional[FlowStats]:
        """Return the ``FlowStats`` matching ``spec`` (a ``TrafficSpec``), or ``None``.

        Match key: ``(src_ip, dst_ip, dst_port, protocol)``. The src port
        is ephemeral on the client side and not constrained. For echo
        flows this returns the forward (client→server) flow; the reverse
        flow is available via :meth:`get_flow_stats` (different src/dst).

        O(1) — looks up the snapshot index built by
        :meth:`_snapshot_flow_stats`.
        """
        if not (0 <= spec.src < self._nb_node and 0 <= spec.dst < self._nb_node):
            return None
        if not self._host_iface_addrs:
            return None
        src_ip = self._host_iface_addrs[spec.src]
        dst_ip = self._host_iface_addrs[spec.dst]
        proto = "udp" if isinstance(spec, (UdpFlowSpec,)) or getattr(spec, "protocol", None) == "udp" else "tcp"
        return self._flow_stats_index.get(
            (src_ip, dst_ip, int(spec.port), proto)
        )

    # ------------------------------------------------------------------
    # Topology construction
    # ------------------------------------------------------------------

    def _build_topology(
        self,
        *,
        nb_node: int,
        nb_link: int,
        ocs_tor_link_bw_mbps: int,
        tor_host_link_bw_mbps: int,
        host_link_delay_us: int,
        ocs_link_delay_us: int,
    ) -> None:
        ns = self._ns

        # ---- Nodes ------------------------------------------------------
        host_container = ns.NodeContainer()
        host_container.Create(nb_node)
        tor_container = ns.NodeContainer()
        tor_container.Create(nb_node)
        ocs_container = ns.NodeContainer()
        ocs_container.Create(1)

        self._host_nodes = [host_container.Get(i) for i in range(nb_node)]
        self._tor_nodes = [tor_container.Get(i) for i in range(nb_node)]
        self._ocs_node = ocs_container.Get(0)

        # ---- Internet stack (hosts + host-facing ToR interface only) ----
        internet = ns.InternetStackHelper()
        internet.Install(host_container)
        internet.Install(tor_container)

        # Disable IP forwarding on ToRs — we route at L2 via TorApp's
        # promiscuous handler; the IP layer must not relay packets itself.
        for tor in self._tor_nodes:
            tor.GetObject[ns.Ipv4]().SetAttribute(
                "IpForward", ns.BooleanValue(False)
            )

        # ---- OCS <-> ToR uplinks (no IPs on either side) ----------------
        p2p_uplink = ns.PointToPointHelper()
        p2p_uplink.SetDeviceAttribute(
            "DataRate", ns.StringValue(f"{ocs_tor_link_bw_mbps}Mbps")
        )
        p2p_uplink.SetChannelAttribute(
            "Delay", ns.TimeValue(ns.MicroSeconds(ocs_link_delay_us))
        )

        # Collect devices per ToR for OcsApp port registration.
        ocs_devices = []                                # OCS-side of each uplink
        tor_uplink_devices: Dict[int, list] = {i: [] for i in range(nb_node)}

        # Port-major (link outer, tor inner) so OCS schedule entries from
        # ``gen_ocs_commands()`` land on the right port without translation
        # (matches Toolbox's ``port_id * nb_node + node_id``).
        for link_id in range(nb_link):
            for tor_id in range(nb_node):
                devs = p2p_uplink.Install(
                    self._tor_nodes[tor_id], self._ocs_node
                )
                # devs.Get(0) is on tor, devs.Get(1) is on ocs.
                tor_uplink_devices[tor_id].append(devs.Get(0))
                ocs_devices.append(devs.Get(1))

        # ---- Host <-> ToR links (assigned IPs) --------------------------
        p2p_host = ns.PointToPointHelper()
        p2p_host.SetDeviceAttribute(
            "DataRate", ns.StringValue(f"{tor_host_link_bw_mbps}Mbps")
        )
        p2p_host.SetChannelAttribute(
            "Delay", ns.TimeValue(ns.MicroSeconds(host_link_delay_us))
        )

        addr = ns.Ipv4AddressHelper()
        tor_host_devices: Dict[int, object] = {}
        for tor_id in range(nb_node):
            devs = p2p_host.Install(
                self._host_nodes[tor_id], self._tor_nodes[tor_id]
            )
            addr.SetBase(
                ns.Ipv4Address(f"10.0.{tor_id}.0"),
                ns.Ipv4Mask("255.255.255.0"),
            )
            ifaces = addr.Assign(devs)
            # ifaces.GetAddress(0) belongs to host, GetAddress(1) to ToR
            host_ip = str(ifaces.GetAddress(0))
            tor_ip = str(ifaces.GetAddress(1))
            self._host_iface_addrs.append(host_ip)
            self._ip_to_tor[host_ip] = tor_id
            tor_host_devices[tor_id] = devs.Get(1)

            # Install a default route on the host through the ToR gateway.
            self._install_host_default_route(
                self._host_nodes[tor_id], tor_ip
            )

        # ---- OcsApp ----------------------------------------------------
        self._ocs_app = ns.CreateObject["ns3::openoptics::OcsApp"]()
        self._ocs_node.AddApplication(self._ocs_app)
        self._ocs_app.SetSliceDurationUs(self._slice_duration_us)
        self._ocs_app.SetNumSlices(self._nb_time_slices)
        # Dark window at the tail of each slice — packets arriving in it
        # are dropped, matching real OCS reconfiguration behaviour.
        self._ocs_app.SetGuardbandUs(self._guardband_us)
        for dev in ocs_devices:
            self._ocs_app.AddPort(dev)
        # Start immediately so RegisterProtocolHandler fires before traffic.
        self._ocs_app.SetStartTime(ns.Seconds(0.0))

        # Map (tor_id, link_id) -> flat OCS port index. ocs_devices were
        # appended above in matching port-major order.
        self._ocs_port_of = lambda tor_id, link_id: ocs_port_index(
            tor_id, link_id, nb_node
        )

        # ---- TorApp ----------------------------------------------------
        uplink_rate_bps = int(ocs_tor_link_bw_mbps) * 1_000_000
        for tor_id in range(nb_node):
            app = ns.CreateObject["ns3::openoptics::TorApp"]()
            self._tor_nodes[tor_id].AddApplication(app)
            app.SetTorId(tor_id)
            app.SetSliceDurationUs(self._slice_duration_us)
            app.SetNumSlices(self._nb_time_slices)
            app.SetCalendarQueueBufferCapacityBytes(self._cq_buffer_bytes)
            app.SetHostDevice(tor_host_devices[tor_id])
            for uplink_dev in tor_uplink_devices[tor_id]:
                app.AddUplinkDevice(uplink_dev)
            # Per-slice byte budget = link rate × (slice − guardband −
            # ocs_delay). The ToR uses this to cap drainable bytes so the
            # last byte arrives before the OCS goes dark.
            app.SetUplinkLinkRateBps(uplink_rate_bps)
            app.SetGuardbandUs(self._guardband_us)
            app.SetUplinkPropagationDelayUs(ocs_link_delay_us)
            app.SetVerifySrCurNode(self._verify_sr_cur_node)
            app.SetAdmissionControl(self._admission_control)
            app.SetStartTime(ns.Seconds(0.0))
            self._tor_apps[tor_id] = app

        # ---- FlowMonitor ----------------------------------------------
        # Hosts are the only flow endpoints. ToRs have IP stacks but the
        # L2 promiscuous handler consumes packets before IP sees them, so
        # FlowMonitor on ToRs would record nothing.
        self._flow_helper = ns.FlowMonitorHelper()
        host_container = ns.NodeContainer()
        for h in self._host_nodes:
            host_container.Add(h)
        self._flow_monitor = self._flow_helper.Install(host_container)

    def _install_host_default_route(self, node, gateway_ip: str) -> None:
        """Install a default route on ``node`` via ``gateway_ip``.

        Mostly symbolic — the host has one interface, but the IP layer
        still needs *some* route for ``Socket::Connect`` to succeed.
        """
        ns = self._ns
        ipv4 = node.GetObject[ns.Ipv4]()
        routing_helper = ns.Ipv4StaticRoutingHelper()
        static_routing = routing_helper.GetStaticRouting(ipv4)
        # Interface 1 is the P2P device (index 0 is the loopback).
        static_routing.SetDefaultRoute(ns.Ipv4Address(gateway_ip), 1)

    # ------------------------------------------------------------------
    # TableEntry dispatch
    # ------------------------------------------------------------------

    def _apply_entry(self, switch_name: str, entry: TableEntry) -> None:
        table = entry.table
        if table in _IGNORED_TABLES:
            return

        if switch_name == "ocs" and table == "ocs_schedule":
            ingress = int(entry.match_keys["ingress_port"])
            slice_id = int(entry.match_keys["slice_id"])
            egress = int(entry.action_params["egress_port"])
            # Toolbox's port-major encoding matches _build_topology's
            # registration order, so values pass through unchanged.
            self._ocs_app.AddScheduleEntry(ingress, slice_id, egress)
            return

        if switch_name.startswith("tor") and table == "ip_to_dst_node":
            tor_id = int(switch_name[3:])
            ip = str(entry.match_keys["ip"])
            dst_node = int(entry.action_params["dst_node"])
            self._tor_apps[tor_id].AddIpToDst(ip, dst_node)
            return

        if switch_name.startswith("tor") and table == "per_hop_routing":
            tor_id = int(switch_name[3:])
            dst = int(entry.match_keys["dst"])
            arrival_ts = int(entry.match_keys["arrival_ts"])
            cur_node = int(entry.action_params.get("cur_node", tor_id))
            send_ts = int(entry.action_params["send_ts"])
            send_port = int(entry.action_params["send_port"])
            self._tor_apps[tor_id].AddPerHopEntry(
                dst, arrival_ts, cur_node, send_ts, send_port
            )
            return

        if switch_name.startswith("tor") and table == "arrive_at_dst":
            tor_id = int(switch_name[3:])
            # The TableEntry's match key is historically called "tor_id" but
            # is matched against OpenOpticsHeader.dst_node in the data plane.
            dst_node = int(entry.match_keys["tor_id"])
            host_port = int(entry.action_params["host_port"])
            self._tor_apps[tor_id].AddArriveAtDst(dst_node, host_port)
            return

        if (switch_name.startswith("tor")
                and table == "cal_port_slice_to_node"):
            tor_id = int(switch_name[3:])
            dst = int(entry.match_keys["dst"])
            arrival_ts = int(entry.match_keys["arrival_ts"])
            send_port = int(entry.action_params["send_port"])
            send_ts = int(entry.action_params["send_ts"])
            self._tor_apps[tor_id].AddCalPortSliceToNode(
                dst, arrival_ts, send_port, send_ts
            )
            return

        if (switch_name.startswith("tor")
                and table == "add_source_routing_entries"):
            if self._admission_control and not self._sr_adm_warned:
                warnings.warn(
                    "[ns3 backend] admission_control=True is a no-op for "
                    "source-routed traffic — ADM only gates the per-hop "
                    "forwarding path (HandleRoutedPacket). Set "
                    "routing_mode=\"Per-hop\" if you want byte-budget "
                    "admission, or drop admission_control to silence this "
                    "warning.",
                    RuntimeWarning,
                    stacklevel=2,
                )
                self._sr_adm_warned = True
            tor_id = int(switch_name[3:])
            dst = int(entry.match_keys["dst"])
            arrival_ts = int(entry.match_keys["arrival_ts"])
            hops_raw = entry.action_params["hops"]
            # Explicit std::vector<Hop> — cppyy can convert Python lists
            # of struct-typed items, but spelling the type out makes the
            # wire format obvious.
            import cppyy
            hop_vec = cppyy.gbl.std.vector[
                "ns3::openoptics::OpenOpticsSourceRouteHeader::Hop"
            ]()
            for hop_tuple in hops_raw:
                cur_node, send_ts, send_port_or_node = hop_tuple
                h = self._ns.openoptics.OpenOpticsSourceRouteHeader.Hop()
                h.cur_node = int(cur_node)
                h.send_ts = int(send_ts)
                h.send_port_or_node = int(send_port_or_node)
                hop_vec.push_back(h)
            self._tor_apps[tor_id].AddSourceRoutingEntry(
                dst, arrival_ts, hop_vec
            )
            return

        raise NotImplementedError(
            f"Ns3Backend cannot dispatch TableEntry on switch={switch_name!r} "
            f"table={table!r}. Entry was: {entry}"
        )
