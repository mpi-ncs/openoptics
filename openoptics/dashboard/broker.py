# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# Author: Yiming Lei (ylei@mpi-inf.mpg.de)
#
# License: Creative Commons NC BY SA 4.0
# https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en
"""In-process async pub/sub broker.

Collectors (running in their own threads) call :meth:`EventBroker.publish_threadsafe`;
WebSocket handlers call :meth:`EventBroker.subscribe` to get an ``asyncio.Queue``
of events. On subscriber-queue overflow the oldest event is dropped (the live
view is best-effort; the full history always lands in the DB via the repository).
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager
from typing import Iterator, Optional, Set

from .events import Event

log = logging.getLogger(__name__)


class EventBroker:
    def __init__(self, queue_size: int = 256):
        self._queue_size = queue_size
        self._subscribers: Set[asyncio.Queue] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Register the asyncio loop where subscriber queues live.

        Called once by :class:`DashboardService` after the uvicorn loop starts.
        """
        self._loop = loop

    async def publish(self, event: Event) -> None:
        for q in list(self._subscribers):
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(event)

    def publish_threadsafe(self, event: Event) -> None:
        """Publish from a non-loop thread (collectors).

        Silently drops if no loop is bound (no subscribers yet) or the loop
        has been closed (web server never started / already shut down). The
        full-history copy of each event still lands in the repository; the
        broker fan-out is best-effort for live subscribers only.
        """
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(self.publish(event), loop)
        except RuntimeError:
            # Loop was closed between the is_closed() check and the call.
            pass

    @contextmanager
    def subscribe(self) -> Iterator[asyncio.Queue]:
        # Auto-bind to the running loop the first time someone subscribes.
        # DashboardService binds explicitly in advance; tests using TestClient
        # never go through that path, so they rely on this fallback.
        if self._loop is None:
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                pass
        q: asyncio.Queue = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers.add(q)
        try:
            yield q
        finally:
            self._subscribers.discard(q)
