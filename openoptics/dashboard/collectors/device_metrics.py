# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# Author: Yiming Lei (ylei@mpi-inf.mpg.de)
#
# License: Creative Commons NC BY SA 4.0
# https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en
"""Collector that polls a :class:`DeviceManager` and emits queue/loss events.

This replaces the old ``Dashboard.update_db`` loop. Unlike the old code it
does not touch any ORM and does not manually trigger any framework signals —
it just yields :class:`MetricSample` objects, which the base class persists
and fans out to live subscribers.
"""
from __future__ import annotations

import time
from typing import Iterable, List

from ..events import Event, MetricSample
from .base import Collector

AGGREGATE_DEVICE = "network"


class DeviceMetricCollector(Collector):
    def __init__(
        self,
        device_manager,
        nb_port: int = 1,
        nb_queue: int = 1,
        interval_s: float = 1.0,
    ):
        super().__init__(interval_s=interval_s, name="DeviceMetricCollector")
        self._dm = device_manager
        self._nb_port = nb_port
        self._nb_queue = nb_queue

    def _sample(self, timestep: int) -> Iterable[Event]:
        now = time.time()
        metrics = self._dm.get_device_metric()
        events: List[Event] = []

        for switch in self._dm.switches:
            name = switch.name
            per_switch = metrics.get(name, {})
            pq_depths = per_switch.get("pq_depth", {}) or {}

            total_depth = 0

            if not pq_depths:
                # No data yet: emit zeros so the chart has a baseline.
                for port in range(self._nb_port):
                    for queue in range(self._nb_queue):
                        events.append(self._depth_sample(
                            timestep, now, name, port, queue, 0
                        ))
            else:
                for (port, queue), depth in pq_depths.items():
                    d = int(depth or 0)
                    total_depth += d
                    events.append(self._depth_sample(
                        timestep, now, name, port, queue, d
                    ))

            # Per-(port, queue) dequeue latency mean/max, if the ToR target
            # populated them this tick. Converted µs → ms for display; the
            # BMv2-side ring buffer stores µs (i32 field).
            pq_latency = per_switch.get("pq_latency", {}) or {}
            for (port, queue), (lat_mean, lat_max) in pq_latency.items():
                events.append(MetricSample(
                    metric_type="queue_latency_mean",
                    device=name,
                    labels={"port": port, "queue": queue},
                    value=float(lat_mean) / 1000.0,
                    timestep=timestep,
                    timestamp=now,
                    epoch_id=self._epoch_id,
                ))
                events.append(MetricSample(
                    metric_type="queue_latency_max",
                    device=name,
                    labels={"port": port, "queue": queue},
                    value=float(lat_max) / 1000.0,
                    timestep=timestep,
                    timestamp=now,
                    epoch_id=self._epoch_id,
                ))

            drop_ctr = float(per_switch.get("drop_ctr", 0) or 0)
            events.append(MetricSample(
                metric_type="queue_depth",
                device=AGGREGATE_DEVICE,
                labels={"switch": name},
                value=float(total_depth),
                timestep=timestep,
                timestamp=now,
                epoch_id=self._epoch_id,
            ))
            events.append(MetricSample(
                metric_type="drop_count",
                device=AGGREGATE_DEVICE,
                labels={"switch": name},
                value=drop_ctr,
                timestep=timestep,
                timestamp=now,
                epoch_id=self._epoch_id,
            ))

        # OCS schedule hit/miss counters. Optional: backends without optical
        # switches return {} and no OCS samples are emitted.
        ocs_metric_fn = getattr(self._dm, "get_ocs_metric", None)
        if ocs_metric_fn is not None:
            try:
                ocs_metrics = ocs_metric_fn()
            except Exception:
                ocs_metrics = {}
            for sw_name, per_port in ocs_metrics.items():
                for port, (hits, misses) in per_port.items():
                    events.append(MetricSample(
                        metric_type="ocs_schedule_hit",
                        device=sw_name,
                        labels={"port": port},
                        value=float(hits),
                        timestep=timestep,
                        timestamp=now,
                        epoch_id=self._epoch_id,
                    ))
                    events.append(MetricSample(
                        metric_type="ocs_schedule_miss",
                        device=sw_name,
                        labels={"port": port},
                        value=float(misses),
                        timestep=timestep,
                        timestamp=now,
                        epoch_id=self._epoch_id,
                    ))

        return events

    def _depth_sample(
        self,
        timestep: int,
        ts: float,
        device: str,
        port: int,
        queue: int,
        depth: int,
    ) -> MetricSample:
        return MetricSample(
            metric_type="queue_depth",
            device=device,
            labels={"port": port, "queue": queue},
            value=float(depth),
            timestep=timestep,
            timestamp=ts,
            epoch_id=self._epoch_id,
        )
