# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# Author: Yiming Lei (ylei@mpi-inf.mpg.de)
#
# License: Creative Commons NC BY SA 4.0
# https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en
"""Base class for telemetry collectors.

Subclasses implement :meth:`_sample` to produce one batch of events per tick.
The base class owns the polling thread, timing, shutdown, and publishing to
both the repository (history) and the broker (live WebSocket feed).
"""
from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from typing import Iterable, Optional

from ..broker import EventBroker
from ..events import Event, MetricSample
from ..storage.repository import Repository

log = logging.getLogger(__name__)


class Collector(ABC):
    def __init__(self, interval_s: float = 1.0, name: Optional[str] = None):
        self.interval_s = interval_s
        self.name = name or self.__class__.__name__
        self._repo: Optional[Repository] = None
        self._broker: Optional[EventBroker] = None
        self._epoch_id: Optional[int] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._timestep = 0

    def bind(self, repo: Repository, broker: EventBroker, epoch_id: int) -> None:
        """Attached by :class:`DashboardService` just before :meth:`start`."""
        self._repo = repo
        self._broker = broker
        self._epoch_id = epoch_id

    @abstractmethod
    def _sample(self, timestep: int) -> Iterable[Event]:
        """Produce events for one polling tick."""

    def start(self) -> None:
        if self._repo is None or self._broker is None or self._epoch_id is None:
            raise RuntimeError(f"{self.name} used before bind()")
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name=self.name, daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def _run(self) -> None:
        # Mirror the old behaviour: a short settling delay so the backend has
        # time to actually create switches before the first poll.
        if self._stop.wait(1.0):
            return
        while not self._stop.is_set():
            tick_start = time.monotonic()
            try:
                events = list(self._sample(self._timestep))
            except Exception:
                log.exception("%s: _sample raised; skipping tick", self.name)
                events = []
            if events:
                samples = [e for e in events if isinstance(e, MetricSample)]
                if samples:
                    try:
                        self._repo.insert_samples(samples)
                    except Exception:
                        log.exception("%s: repo.insert_samples failed", self.name)
                for ev in events:
                    self._broker.publish_threadsafe(ev)
            self._timestep += 1
            elapsed = time.monotonic() - tick_start
            if self._stop.wait(max(0.0, self.interval_s - elapsed)):
                return
