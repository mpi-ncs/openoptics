"""User-facing traffic helpers for the ns-3 backend.

The builders in this module stay pure Python on purpose. They turn friendly
traffic descriptions (rates, durations, traffic matrices, common patterns)
into concrete ns-3 application installs performed by :class:`Ns3Backend`.
That keeps validation easy to unit-test in environments without ns-3.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from math import ceil, floor
import re
from typing import Iterable, List, Mapping, Optional, Sequence, Tuple, Union


Number = Union[int, float]
RateValue = Union[str, Number]


_BITRATE_UNITS = {
    "bps": 1.0,
    "b/s": 1.0,
    "bit/s": 1.0,
    "bits/s": 1.0,
    "kbps": 1e3,
    "kbit/s": 1e3,
    "kbits/s": 1e3,
    "mbps": 1e6,
    "mbit/s": 1e6,
    "mbits/s": 1e6,
    "gbps": 1e9,
    "gbit/s": 1e9,
    "gbits/s": 1e9,
}
_SHORT_BITRATE_UNITS = {
    "": "bps",
    "k": "kbps",
    "m": "mbps",
    "g": "gbps",
}
_BITRATE_RE = re.compile(
    r"^\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>[a-zA-Z/]+)?\s*$"
)


def parse_bitrate(value: RateValue, *, default_unit: str = "bps") -> float:
    """Return a bitrate in bits per second.

    ``value`` may be numeric (interpreted in ``default_unit``) or a string such
    as ``"10Mbps"``, ``"500 kbit/s"``, or ``"1G"``.
    """
    if isinstance(value, (int, float)):
        unit = _normalize_bitrate_unit(default_unit)
        rate = float(value) * _BITRATE_UNITS[unit]
        if rate <= 0:
            raise ValueError("bitrate must be positive")
        return rate

    match = _BITRATE_RE.match(str(value))
    if not match:
        raise ValueError(f"invalid bitrate: {value!r}")

    amount = float(match.group("value"))
    unit_text = match.group("unit")
    if unit_text is None:
        unit = _normalize_bitrate_unit(default_unit)
    else:
        unit = _normalize_bitrate_unit(unit_text)
    rate = amount * _BITRATE_UNITS[unit]
    if rate <= 0:
        raise ValueError("bitrate must be positive")
    return rate


def _normalize_bitrate_unit(unit: str) -> str:
    cleaned = unit.strip().lower().replace(" ", "")
    cleaned = _SHORT_BITRATE_UNITS.get(cleaned, cleaned)
    if cleaned not in _BITRATE_UNITS:
        raise ValueError(
            f"unknown bitrate unit {unit!r}; use bps, Kbps, Mbps, or Gbps"
        )
    return cleaned


@dataclass(frozen=True)
class UdpFlowSpec:
    """Resolved one-way or echo UDP traffic."""

    src: int
    dst: int
    start_s: float
    stop_s: float
    num_packets: int
    packet_size_bytes: int
    interval_s: float
    mode: str = "client-server"
    size_bytes: Optional[int] = None
    rate_bps: Optional[float] = None
    port: Optional[int] = None
    name: Optional[str] = None

    @property
    def protocol(self) -> str:
        return "udp"

    @property
    def duration_s(self) -> float:
        return self.stop_s - self.start_s

    @property
    def offered_rate_bps(self) -> float:
        return self.packet_size_bytes * 8.0 / self.interval_s

    def with_port(self, port: int) -> "UdpFlowSpec":
        return replace(self, port=port)


@dataclass(frozen=True)
class TcpBulkFlowSpec:
    """Resolved TCP BulkSend traffic."""

    src: int
    dst: int
    start_s: float
    stop_s: float
    size_bytes: Optional[int] = None
    chunk_size_bytes: int = 1024
    port: Optional[int] = None
    name: Optional[str] = None

    @property
    def protocol(self) -> str:
        return "tcp"

    @property
    def mode(self) -> str:
        return "bulk"

    @property
    def duration_s(self) -> float:
        return self.stop_s - self.start_s

    @property
    def max_bytes(self) -> int:
        return 0 if self.size_bytes is None else self.size_bytes

    def with_port(self, port: int) -> "TcpBulkFlowSpec":
        return replace(self, port=port)


@dataclass(frozen=True)
class OnOffFlowSpec:
    """Resolved rate-shaped OnOff traffic for TCP or UDP."""

    src: int
    dst: int
    protocol: str
    start_s: float
    stop_s: float
    rate_bps: float
    max_bytes: int = 0
    packet_size_bytes: int = 1024
    port: Optional[int] = None
    name: Optional[str] = None

    @property
    def mode(self) -> str:
        return "onoff"

    @property
    def duration_s(self) -> float:
        return self.stop_s - self.start_s

    def with_port(self, port: int) -> "OnOffFlowSpec":
        return replace(self, port=port)


TrafficSpec = Union[UdpFlowSpec, TcpBulkFlowSpec, OnOffFlowSpec]


@dataclass(frozen=True)
class FlowStats:
    """Per-flow end-to-end stats from ns-3's ``FlowMonitor``.

    All times are seconds; ``nan`` is used where a quantity is undefined
    (e.g. delays when nothing was received). ``fct_s`` is the flow
    completion time (``timeLastRxPacket - timeFirstTxPacket``).
    """

    src_ip: str
    dst_ip: str
    src_port: int
    dst_port: int
    protocol: str            # "udp", "tcp", or numeric string
    tx_packets: int
    rx_packets: int
    lost_packets: int
    tx_bytes: int
    rx_bytes: int
    delay_avg_s: float
    delay_min_s: float
    delay_max_s: float
    jitter_avg_s: float
    fct_s: float
    throughput_bps: float


@dataclass(frozen=True)
class InstalledTraffic:
    """Result returned by a traffic builder's ``install()`` method."""

    spec: TrafficSpec
    apps: object
    _backend: Optional[object] = None

    def stats(self) -> Optional[FlowStats]:
        """Return ``FlowStats`` for this flow, or ``None`` if unavailable.

        Available after ``net.start()`` (which runs the simulator and
        populates ``FlowMonitor``). Returns ``None`` when the simulation
        hasn't run, the FlowMonitor has no record matching this spec's
        5-tuple, or the backend predates the stats accessor.
        """
        backend = self._backend
        if backend is None:
            return None
        lookup = getattr(backend, "flow_stats_for", None)
        if lookup is None:
            return None
        return lookup(self.spec)


class _TrafficBuilderBase:
    """Shared validation and install lifecycle for ns-3 traffic builders."""

    def __init__(self, backend, *, port_base: int = 9000) -> None:
        self._backend = backend
        self._next_port = int(port_base)
        self._flows: List[TrafficSpec] = []
        self._installed = False

    @property
    def flows(self) -> Tuple[TrafficSpec, ...]:
        return tuple(self._flows)

    def _before_install(self) -> None:
        if self._installed:
            raise RuntimeError("traffic builders can be installed only once")

    def _after_install(self, resolved: List[TrafficSpec]) -> None:
        self._flows = resolved
        self._installed = True

    def _ensure_mutable(self) -> None:
        if self._installed:
            raise RuntimeError("cannot add traffic after install()")

    def _validate_node_pair(self, src: int, dst: int) -> None:
        nb_node = int(getattr(self._backend, "_nb_node", 0))
        if nb_node > 0:
            if not (0 <= src < nb_node and 0 <= dst < nb_node):
                raise IndexError(f"src={src} dst={dst} out of range 0..{nb_node - 1}")
        if src == dst:
            raise ValueError("self traffic is not supported; src and dst differ")

    def _validate_start(self, start_s: Number) -> float:
        start = float(start_s)
        if start < 0:
            raise ValueError("start_s must be non-negative")
        return start

    def _resolve_stop(
        self,
        *,
        start_s: float,
        stop_s: Optional[Number],
        duration_s: Optional[Number],
        num_packets: Optional[int] = None,
        interval_s: Optional[float] = None,
    ) -> float:
        if stop_s is not None and duration_s is not None:
            raise ValueError("specify only one of stop_s or duration_s")
        if duration_s is not None:
            if float(duration_s) <= 0:
                raise ValueError("duration_s must be positive")
            return start_s + float(duration_s)
        if stop_s is not None:
            return float(stop_s)
        if num_packets is not None and interval_s is not None:
            return start_s + int(num_packets) * interval_s
        return float(getattr(self._backend, "_simulation_stop_s", start_s + 1.0))

    def _allocate_port(self) -> int:
        allocator = getattr(self._backend, "_allocate_traffic_port", None)
        if allocator is not None:
            return int(allocator())
        port = self._next_port
        self._next_port += 1
        return port

    def _all_nodes(self) -> range:
        nb_node = int(getattr(self._backend, "_nb_node", 0))
        if nb_node <= 0:
            raise RuntimeError("nodes must be provided before backend setup()")
        return range(nb_node)


class UdpTrafficGenerator(_TrafficBuilderBase):
    """Builder for UDP traffic workloads.

    Typical usage::

        net.udp_traffic() \\
            .flow(0, 1, rate="10Mbps", duration_s=0.5) \\
            .echo(2, 3, num_packets=20, interval_s=0.03) \\
            .install()

    Call ``install()`` after ``deploy_routing()`` and before ``net.start()``.
    """

    def flow(
        self,
        src: int,
        dst: int,
        *,
        rate: Optional[RateValue] = None,
        packets_per_second: Optional[Number] = None,
        start_s: Number = 0.05,
        stop_s: Optional[Number] = None,
        duration_s: Optional[Number] = None,
        size_bytes: Optional[int] = None,
        num_packets: Optional[int] = None,
        interval_s: Optional[Number] = None,
        packet_size_bytes: int = 1024,
        port: Optional[int] = None,
        name: Optional[str] = None,
    ) -> "UdpTrafficGenerator":
        """Add one one-way UDP client/server flow."""
        self._ensure_mutable()
        self._flows.append(
            self._make_udp_flow(
                src=src,
                dst=dst,
                mode="client-server",
                rate=rate,
                packets_per_second=packets_per_second,
                start_s=start_s,
                stop_s=stop_s,
                duration_s=duration_s,
                size_bytes=size_bytes,
                num_packets=num_packets,
                interval_s=interval_s,
                packet_size_bytes=packet_size_bytes,
                port=port,
                name=name,
            )
        )
        return self

    constant_rate = flow

    def echo(
        self,
        src: int,
        dst: int,
        *,
        rate: Optional[RateValue] = None,
        packets_per_second: Optional[Number] = None,
        start_s: Number = 0.05,
        stop_s: Optional[Number] = None,
        duration_s: Optional[Number] = None,
        size_bytes: Optional[int] = None,
        num_packets: Optional[int] = None,
        interval_s: Optional[Number] = None,
        packet_size_bytes: int = 1024,
        port: Optional[int] = None,
        name: Optional[str] = None,
    ) -> "UdpTrafficGenerator":
        """Add one UDP echo request/reply flow."""
        self._ensure_mutable()
        self._flows.append(
            self._make_udp_flow(
                src=src,
                dst=dst,
                mode="echo",
                rate=rate,
                packets_per_second=packets_per_second,
                start_s=start_s,
                stop_s=stop_s,
                duration_s=duration_s,
                size_bytes=size_bytes,
                num_packets=num_packets,
                interval_s=interval_s,
                packet_size_bytes=packet_size_bytes,
                port=port,
                name=name,
            )
        )
        return self

    def onoff(
        self,
        src: int,
        dst: int,
        *,
        rate: Optional[RateValue] = None,
        start_s: Number = 0.05,
        stop_s: Optional[Number] = None,
        duration_s: Optional[Number] = None,
        size_bytes: Optional[int] = None,
        packet_size_bytes: int = 1024,
        port: Optional[int] = None,
        name: Optional[str] = None,
    ) -> "UdpTrafficGenerator":
        """Add one rate-shaped UDP OnOff flow."""
        self._ensure_mutable()
        self._flows.append(
            self._make_onoff_flow(
                protocol="udp",
                src=src,
                dst=dst,
                rate=rate,
                start_s=start_s,
                stop_s=stop_s,
                duration_s=duration_s,
                size_bytes=size_bytes,
                packet_size_bytes=packet_size_bytes,
                port=port,
                name=name,
            )
        )
        return self

    def bidirectional(self, a: int, b: int, **kwargs) -> "UdpTrafficGenerator":
        """Add ``a -> b`` and ``b -> a`` one-way UDP flows."""
        self.flow(a, b, **kwargs)
        self.flow(b, a, **kwargs)
        return self

    def many_to_one(
        self,
        sources: Iterable[int],
        dst: int,
        **kwargs,
    ) -> "UdpTrafficGenerator":
        """Add one one-way UDP flow from every source in ``sources`` to ``dst``."""
        for src in sources:
            if int(src) == int(dst):
                continue
            self.flow(int(src), int(dst), **kwargs)
        return self

    def all_to_all(
        self,
        nodes: Optional[Iterable[int]] = None,
        *,
        include_self: bool = False,
        **kwargs,
    ) -> "UdpTrafficGenerator":
        """Add every ordered source/destination pair as one-way UDP traffic."""
        node_ids = list(self._all_nodes() if nodes is None else nodes)
        for src in node_ids:
            for dst in node_ids:
                if not include_self and int(src) == int(dst):
                    continue
                self.flow(int(src), int(dst), **kwargs)
        return self

    def from_matrix(
        self,
        matrix,
        *,
        skip_zero: bool = True,
        include_self: bool = False,
        **kwargs,
    ) -> "UdpTrafficGenerator":
        """Add one-way UDP flows from a traffic matrix.

        ``matrix`` may be either a mapping ``{(src, dst): rate}`` or a
        rectangular sequence where ``matrix[src][dst]`` is the rate. Values use
        the same semantics as ``flow(..., rate=...)``.
        """
        conflicts = {"rate", "packets_per_second", "interval_s"} & set(kwargs)
        if conflicts:
            names = ", ".join(sorted(conflicts))
            raise ValueError(
                f"from_matrix values provide rates; do not pass {names}"
            )
        for src, dst, value in _iter_matrix_entries(matrix):
            if not include_self and src == dst:
                continue
            if value is None:
                continue
            if skip_zero and isinstance(value, (int, float)) and float(value) == 0:
                continue
            self.flow(src, dst, rate=value, **kwargs)
        return self

    def install(self) -> List[InstalledTraffic]:
        """Install all queued UDP flows on the backend and return app handles."""
        self._before_install()
        installed: List[InstalledTraffic] = []
        resolved: List[TrafficSpec] = []
        for spec in self._flows:
            if spec.port is None:
                spec = spec.with_port(self._allocate_port())
            if isinstance(spec, UdpFlowSpec) and spec.mode == "client-server":
                apps = self._backend.install_udp_flow(
                    src=spec.src,
                    dst=spec.dst,
                    start_s=spec.start_s,
                    stop_s=spec.stop_s,
                    num_packets=spec.num_packets,
                    packet_size_bytes=spec.packet_size_bytes,
                    interval_s=spec.interval_s,
                    port=spec.port,
                )
            elif isinstance(spec, UdpFlowSpec) and spec.mode == "echo":
                apps = self._backend.install_udp_echo_flow(
                    src=spec.src,
                    dst=spec.dst,
                    start_s=spec.start_s,
                    stop_s=spec.stop_s,
                    num_packets=spec.num_packets,
                    packet_size_bytes=spec.packet_size_bytes,
                    interval_s=spec.interval_s,
                    port=spec.port,
                )
            elif isinstance(spec, OnOffFlowSpec) and spec.protocol == "udp":
                apps = self._backend.install_onoff_flow(
                    src=spec.src,
                    dst=spec.dst,
                    protocol="udp",
                    start_s=spec.start_s,
                    stop_s=spec.stop_s,
                    rate_bps=spec.rate_bps,
                    max_bytes=spec.max_bytes,
                    packet_size_bytes=spec.packet_size_bytes,
                    port=spec.port,
                )
            else:  # pragma: no cover; builder methods prevent this.
                raise ValueError(f"unsupported UDP traffic spec: {spec!r}")
            resolved.append(spec)
            installed.append(
                InstalledTraffic(spec=spec, apps=apps, _backend=self._backend)
            )
        self._after_install(resolved)
        return installed

    def describe(self) -> List[dict]:
        """Return a serializable summary of queued UDP flows."""
        rows = []
        for index, spec in enumerate(self._flows):
            if isinstance(spec, UdpFlowSpec):
                rows.append(
                    {
                        "name": spec.name or f"flow{index}",
                        "protocol": "udp",
                        "mode": spec.mode,
                        "src": spec.src,
                        "dst": spec.dst,
                        "start_s": spec.start_s,
                        "stop_s": spec.stop_s,
                        "duration_s": spec.duration_s,
                        "size_bytes": spec.size_bytes,
                        "rate_bps": spec.rate_bps,
                        "num_packets": spec.num_packets,
                        "packet_size_bytes": spec.packet_size_bytes,
                        "interval_s": spec.interval_s,
                        "offered_rate_mbps": spec.offered_rate_bps / 1e6,
                        "port": spec.port,
                    }
                )
            elif isinstance(spec, OnOffFlowSpec):
                rows.append(_describe_onoff(spec, index))
        return rows

    def _make_udp_flow(
        self,
        *,
        src: int,
        dst: int,
        mode: str,
        rate: Optional[RateValue],
        packets_per_second: Optional[Number],
        start_s: Number,
        stop_s: Optional[Number],
        duration_s: Optional[Number],
        size_bytes: Optional[int],
        num_packets: Optional[int],
        interval_s: Optional[Number],
        packet_size_bytes: int,
        port: Optional[int],
        name: Optional[str],
    ) -> UdpFlowSpec:
        src = int(src)
        dst = int(dst)
        self._validate_node_pair(src, dst)
        start = self._validate_start(start_s)

        if int(packet_size_bytes) <= 0:
            raise ValueError("packet_size_bytes must be positive")
        if size_bytes is not None and int(size_bytes) <= 0:
            raise ValueError("size_bytes must be positive")

        rate_bps = None
        specified_rates = 0
        if rate is not None:
            rate_bps = parse_bitrate(rate)
            specified_rates += 1
        if packets_per_second is not None:
            specified_rates += 1
        if interval_s is not None:
            specified_rates += 1
        if specified_rates > 1:
            raise ValueError(
                "specify only one of rate, packets_per_second, or interval_s"
            )

        if rate_bps is not None:
            if rate_bps <= 0:
                raise ValueError("rate must be positive")
            interval = int(packet_size_bytes) * 8.0 / rate_bps
        elif packets_per_second is not None:
            if float(packets_per_second) <= 0:
                raise ValueError("packets_per_second must be positive")
            interval = 1.0 / float(packets_per_second)
        elif interval_s is not None:
            interval = float(interval_s)
        else:
            interval = 0.01
        if interval <= 0:
            raise ValueError("interval_s must be positive")

        if size_bytes is not None and num_packets is not None:
            raise ValueError("specify only one of size_bytes or num_packets")
        if size_bytes is not None:
            num_packets = int(ceil(float(size_bytes) / int(packet_size_bytes)))

        stop = self._resolve_stop(
            start_s=start,
            stop_s=stop_s,
            duration_s=duration_s,
            num_packets=num_packets,
            interval_s=interval,
        )
        if stop <= start:
            raise ValueError("stop_s must be greater than start_s")

        if num_packets is None:
            num_packets = max(1, floor((stop - start) / interval))
        if int(num_packets) <= 0:
            raise ValueError("num_packets must be positive")

        return UdpFlowSpec(
            src=src,
            dst=dst,
            start_s=start,
            stop_s=stop,
            num_packets=int(num_packets),
            packet_size_bytes=int(packet_size_bytes),
            interval_s=float(interval),
            mode=mode,
            size_bytes=None if size_bytes is None else int(size_bytes),
            rate_bps=rate_bps,
            port=None if port is None else int(port),
            name=name,
        )

    def _make_onoff_flow(self, **kwargs) -> OnOffFlowSpec:
        return _make_onoff_flow(self, **kwargs)


class TcpTrafficGenerator(_TrafficBuilderBase):
    """Builder for TCP traffic workloads."""

    def bulk(
        self,
        src: int,
        dst: int,
        *,
        size_bytes: Optional[int] = None,
        chunk_size_bytes: int = 1024,
        start_s: Number = 0.05,
        stop_s: Optional[Number] = None,
        duration_s: Optional[Number] = None,
        port: Optional[int] = None,
        name: Optional[str] = None,
    ) -> "TcpTrafficGenerator":
        """Add one TCP BulkSend flow.

        ``size_bytes=None`` means ns-3 BulkSend sends until ``stop_s``.
        """
        self._ensure_mutable()
        self._flows.append(
            self._make_bulk_flow(
                src=src,
                dst=dst,
                size_bytes=size_bytes,
                chunk_size_bytes=chunk_size_bytes,
                start_s=start_s,
                stop_s=stop_s,
                duration_s=duration_s,
                port=port,
                name=name,
            )
        )
        return self

    def onoff(
        self,
        src: int,
        dst: int,
        *,
        rate: Optional[RateValue] = None,
        start_s: Number = 0.05,
        stop_s: Optional[Number] = None,
        duration_s: Optional[Number] = None,
        size_bytes: Optional[int] = None,
        packet_size_bytes: int = 1024,
        port: Optional[int] = None,
        name: Optional[str] = None,
    ) -> "TcpTrafficGenerator":
        """Add one rate-shaped TCP OnOff flow."""
        self._ensure_mutable()
        self._flows.append(
            self._make_onoff_flow(
                protocol="tcp",
                src=src,
                dst=dst,
                rate=rate,
                start_s=start_s,
                stop_s=stop_s,
                duration_s=duration_s,
                size_bytes=size_bytes,
                packet_size_bytes=packet_size_bytes,
                port=port,
                name=name,
            )
        )
        return self

    def install(self) -> List[InstalledTraffic]:
        """Install all queued TCP flows on the backend and return app handles."""
        self._before_install()
        installed: List[InstalledTraffic] = []
        resolved: List[TrafficSpec] = []
        for spec in self._flows:
            if spec.port is None:
                spec = spec.with_port(self._allocate_port())
            if isinstance(spec, TcpBulkFlowSpec):
                apps = self._backend.install_tcp_bulk_flow(
                    src=spec.src,
                    dst=spec.dst,
                    start_s=spec.start_s,
                    stop_s=spec.stop_s,
                    max_bytes=spec.max_bytes,
                    send_size_bytes=spec.chunk_size_bytes,
                    port=spec.port,
                )
            elif isinstance(spec, OnOffFlowSpec) and spec.protocol == "tcp":
                apps = self._backend.install_onoff_flow(
                    src=spec.src,
                    dst=spec.dst,
                    protocol="tcp",
                    start_s=spec.start_s,
                    stop_s=spec.stop_s,
                    rate_bps=spec.rate_bps,
                    max_bytes=spec.max_bytes,
                    packet_size_bytes=spec.packet_size_bytes,
                    port=spec.port,
                )
            else:  # pragma: no cover; builder methods prevent this.
                raise ValueError(f"unsupported TCP traffic spec: {spec!r}")
            resolved.append(spec)
            installed.append(
                InstalledTraffic(spec=spec, apps=apps, _backend=self._backend)
            )
        self._after_install(resolved)
        return installed

    def describe(self) -> List[dict]:
        """Return a serializable summary of queued TCP flows."""
        rows = []
        for index, spec in enumerate(self._flows):
            if isinstance(spec, TcpBulkFlowSpec):
                rows.append(
                    {
                        "name": spec.name or f"flow{index}",
                        "protocol": "tcp",
                        "mode": "bulk",
                        "src": spec.src,
                        "dst": spec.dst,
                        "start_s": spec.start_s,
                        "stop_s": spec.stop_s,
                        "duration_s": spec.duration_s,
                        "size_bytes": spec.size_bytes,
                        "chunk_size_bytes": spec.chunk_size_bytes,
                        "port": spec.port,
                    }
                )
            elif isinstance(spec, OnOffFlowSpec):
                rows.append(_describe_onoff(spec, index))
        return rows

    def _make_bulk_flow(
        self,
        *,
        src: int,
        dst: int,
        size_bytes: Optional[int],
        chunk_size_bytes: int,
        start_s: Number,
        stop_s: Optional[Number],
        duration_s: Optional[Number],
        port: Optional[int],
        name: Optional[str],
    ) -> TcpBulkFlowSpec:
        src = int(src)
        dst = int(dst)
        self._validate_node_pair(src, dst)
        start = self._validate_start(start_s)

        if size_bytes is not None and int(size_bytes) <= 0:
            raise ValueError("size_bytes must be positive")
        if int(chunk_size_bytes) <= 0:
            raise ValueError("chunk_size_bytes must be positive")

        stop = self._resolve_stop(
            start_s=start,
            stop_s=stop_s,
            duration_s=duration_s,
        )
        if stop <= start:
            raise ValueError("stop_s must be greater than start_s")

        return TcpBulkFlowSpec(
            src=src,
            dst=dst,
            start_s=start,
            stop_s=stop,
            size_bytes=None if size_bytes is None else int(size_bytes),
            chunk_size_bytes=int(chunk_size_bytes),
            port=None if port is None else int(port),
            name=name,
        )

    def _make_onoff_flow(self, **kwargs) -> OnOffFlowSpec:
        return _make_onoff_flow(self, **kwargs)


def _make_onoff_flow(
    builder: _TrafficBuilderBase,
    *,
    protocol: str,
    src: int,
    dst: int,
    rate: Optional[RateValue],
    start_s: Number,
    stop_s: Optional[Number],
    duration_s: Optional[Number],
    size_bytes: Optional[int],
    packet_size_bytes: int,
    port: Optional[int],
    name: Optional[str],
) -> OnOffFlowSpec:
    protocol_norm = protocol.strip().lower()
    if protocol_norm not in {"tcp", "udp"}:
        raise ValueError("protocol must be 'tcp' or 'udp'")

    src = int(src)
    dst = int(dst)
    builder._validate_node_pair(src, dst)
    start = builder._validate_start(start_s)

    if size_bytes is not None and int(size_bytes) <= 0:
        raise ValueError("size_bytes must be positive")
    byte_cap = 0 if size_bytes is None else int(size_bytes)
    if int(packet_size_bytes) <= 0:
        raise ValueError("packet_size_bytes must be positive")

    stop = builder._resolve_stop(
        start_s=start,
        stop_s=stop_s,
        duration_s=duration_s,
    )
    if stop <= start:
        raise ValueError("stop_s must be greater than start_s")

    rate_bps = None
    if rate is not None:
        rate_bps = parse_bitrate(rate)
    if rate_bps is None:
        if int(byte_cap) > 0:
            rate_bps = int(byte_cap) * 8.0 / (stop - start)
        else:
            rate_bps = 1_000_000.0
    if rate_bps <= 0:
        raise ValueError("rate must be positive")

    return OnOffFlowSpec(
        src=src,
        dst=dst,
        protocol=protocol_norm,
        start_s=start,
        stop_s=stop,
        rate_bps=float(rate_bps),
        max_bytes=int(byte_cap),
        packet_size_bytes=int(packet_size_bytes),
        port=None if port is None else int(port),
        name=name,
    )


def _describe_onoff(spec: OnOffFlowSpec, index: int) -> dict:
    return {
        "name": spec.name or f"flow{index}",
        "protocol": spec.protocol,
        "mode": "onoff",
        "src": spec.src,
        "dst": spec.dst,
        "start_s": spec.start_s,
        "stop_s": spec.stop_s,
        "duration_s": spec.duration_s,
        "size_bytes": None if spec.max_bytes == 0 else spec.max_bytes,
        "rate_bps": spec.rate_bps,
        "packet_size_bytes": spec.packet_size_bytes,
        "port": spec.port,
    }


def _iter_matrix_entries(matrix):
    if isinstance(matrix, Mapping):
        for key, value in matrix.items():
            if not isinstance(key, tuple) or len(key) != 2:
                raise ValueError("traffic matrix keys must be (src, dst) tuples")
            yield int(key[0]), int(key[1]), value
        return

    if not isinstance(matrix, Sequence):
        raise TypeError("matrix must be a mapping or a rectangular sequence")
    for src, row in enumerate(matrix):
        if isinstance(row, Mapping):
            items = row.items()
        else:
            items = enumerate(row)
        for dst, value in items:
            yield int(src), int(dst), value
