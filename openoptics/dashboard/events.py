# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# Author: Yiming Lei (ylei@mpi-inf.mpg.de)
#
# License: Creative Commons NC BY SA 4.0
# https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en
"""Event types published by collectors and consumed by storage + WebSocket fan-out.

The schema is intentionally generic: a :class:`MetricSample` carries a
``metric_type`` string plus a free-form ``labels`` dict, so new telemetry
kinds (throughput, latency, link utilisation, …) can be added by producers
without any schema change.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Union


@dataclass(frozen=True)
class MetricSample:
    metric_type: str
    device: str
    value: float
    timestep: int
    timestamp: float
    epoch_id: int
    labels: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TopologyUpdate:
    epoch_id: int
    image_url: str
    timestep: int = 0


Event = Union[MetricSample, TopologyUpdate]
