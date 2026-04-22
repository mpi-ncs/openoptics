# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# Author: Yiming Lei (ylei@mpi-inf.mpg.de)
#
# License: Creative Commons NC BY SA 4.0
# https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en
"""Event-driven publisher for traffic-aware reconfig (set_active_queue) events.

Unlike :class:`Collector`, this has no polling thread — :meth:`emit` is called
synchronously from the control plane whenever a queue gate flips. Each call
persists one :class:`MetricSample` with ``metric_type="ta_reconfig"`` and
broadcasts it to live WebSocket subscribers via the broker.
"""
from __future__ import annotations

import itertools
import threading
import time
from typing import Optional

from ..broker import EventBroker
from ..events import MetricSample
from ..storage.repository import Repository

METRIC_TYPE = "ta_reconfig"


class ReconfigEventPublisher:
    def __init__(self) -> None:
        self._repo: Optional[Repository] = None
        self._broker: Optional[EventBroker] = None
        self._epoch_id: Optional[int] = None
        self._lock = threading.Lock()
        self._counter = itertools.count()

    def bind(self, repo: Repository, broker: EventBroker, epoch_id: int) -> None:
        self._repo = repo
        self._broker = broker
        self._epoch_id = epoch_id

    def emit(self, switch_name: str, qid: int) -> None:
        if self._repo is None or self._broker is None or self._epoch_id is None:
            # Dashboard inactive (NullDashboard path) — silently no-op.
            return
        with self._lock:
            timestep = next(self._counter)
        sample = MetricSample(
            metric_type=METRIC_TYPE,
            device=switch_name,
            value=float(qid),
            timestep=timestep,
            timestamp=time.time(),
            epoch_id=self._epoch_id,
            labels={},
        )
        try:
            self._repo.insert_samples([sample])
        except Exception:
            # Persistence failure must not break the control-plane call.
            pass
        self._broker.publish_threadsafe(sample)
