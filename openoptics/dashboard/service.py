# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# Author: Yiming Lei (ylei@mpi-inf.mpg.de)
#
# License: Creative Commons NC BY SA 4.0
# https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en
"""Lifecycle composition: broker + repository + collectors + uvicorn web server.

All of this runs in the same Python process as :class:`BaseNetwork`. The
uvicorn server lives on its own asyncio loop in a dedicated thread so it
can't block the network/CLI.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import List, Optional

from .broker import EventBroker
from .collectors.base import Collector
from .config import DashboardConfig
from .events import TopologyUpdate
from .storage.repository import Epoch, Repository

log = logging.getLogger(__name__)


class DashboardService:
    def __init__(self, config: Optional[DashboardConfig] = None):
        self.config = config or DashboardConfig.from_env()
        self.config.ensure_dirs()

        self.repo = Repository(self.config.db_path)
        self.broker = EventBroker(queue_size=self.config.live_queue_size)
        self.collectors: List[Collector] = []
        self.epoch: Optional[Epoch] = None

        self._server = None  # uvicorn.Server
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None

    # -- epoch ----------------------------------------------------------

    def begin_epoch(self, seed: Optional[str] = None) -> Epoch:
        seed = seed or datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        name = self.repo.next_epoch_display_name(seed)
        self.epoch = self.repo.create_epoch(name)
        return self.epoch

    def update_topology(self, slice_to_topo) -> None:
        """Render ``slice_to_topo`` to a PNG under ``media/topos/`` and publish."""
        if self.epoch is None:
            self.begin_epoch()
        from openoptics.OpticalTopo import draw_topo  # lazy: heavy matplotlib import

        fig = draw_topo(slice_to_topo)
        buffer = BytesIO()
        fig.savefig(buffer, format="png", dpi=300, bbox_inches="tight")
        try:
            import matplotlib.pyplot as plt  # noqa: WPS433
            plt.close(fig)
        except Exception:
            pass

        # One PNG per epoch, overwritten in place on every update. The
        # `?t=<ms>` query string cache-busts the browser so the overwritten
        # image is re-fetched without stale bytes. StaticFiles ignores
        # the query, so the file resolution is identical.
        filename = f"epoch_{self.epoch.id}.png"
        out = self.config.topos_dir / filename
        out.write_bytes(buffer.getvalue())
        url = f"/media/topos/{filename}?t={int(time.time() * 1000)}"
        self.repo.set_epoch_topo_url(self.epoch.id, url)
        self.epoch = Epoch(
            id=self.epoch.id,
            display_name=self.epoch.display_name,
            created_at=self.epoch.created_at,
            topo_image_url=url,
        )
        self.broker.publish_threadsafe(TopologyUpdate(
            epoch_id=self.epoch.id, image_url=url,
        ))

    # -- collectors -----------------------------------------------------

    def register_collector(self, collector: Collector) -> None:
        if self.epoch is None:
            raise RuntimeError("begin_epoch() must be called before register_collector()")
        collector.bind(self.repo, self.broker, self.epoch.id)
        self.collectors.append(collector)

    def register_event_source(self, source) -> None:
        """Bind a non-polling event source (e.g. ``ReconfigEventPublisher``).

        Unlike collectors, event sources have no polling thread; ``start()``/``stop()``
        are not invoked on them. Binding just wires repo/broker/epoch_id so the
        source can persist + broadcast when its ``emit`` method is called.
        """
        if self.epoch is None:
            raise RuntimeError("begin_epoch() must be called before register_event_source()")
        source.bind(self.repo, self.broker, self.epoch.id)

    # -- lifecycle ------------------------------------------------------

    def start(self) -> None:
        self._start_web()
        for c in self.collectors:
            c.start()

    def stop(self) -> None:
        for c in self.collectors:
            try:
                c.stop()
            except Exception:
                log.exception("error stopping collector %s", c.name)
        self._stop_web()
        self.repo.close()

    # -- internals ------------------------------------------------------

    def _start_web(self) -> None:
        import uvicorn  # lazy: dashboard extra may be uninstalled

        from .web.app import create_app

        app = create_app(self.config, self.repo, self.broker)
        cfg = uvicorn.Config(
            app,
            host=self.config.host,
            port=self.config.port,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(cfg)
        server.config.load()
        server.lifespan = server.config.lifespan_class(server.config)
        self._server = server

        started = threading.Event()

        def _runner():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            # Broker loop-binding happens in the FastAPI startup event
            # (see web.app.create_app), so we don't do it here.
            started.set()
            try:
                loop.run_until_complete(server.serve())
            finally:
                loop.close()

        self._loop_thread = threading.Thread(
            target=_runner, name="openoptics-dashboard", daemon=True
        )
        self._loop_thread.start()
        started.wait(timeout=5.0)

        # Wait for uvicorn to bind (server.started) OR for the loop thread to
        # die (e.g. bind failed with OSError; the runner's finally closed the
        # loop and returned). Polling both means we don't wait the full timeout
        # when there's an immediate failure.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if getattr(server, "started", False):
                break
            if self._loop_thread is not None and not self._loop_thread.is_alive():
                break
            time.sleep(0.05)

        if getattr(server, "started", False):
            print(f"Access dashboard at http://{self.config.host}:{self.config.port}")
        else:
            # Bind failure or similar — the loop is closed. Null it out so
            # collector threads don't publish through a dead loop and crash.
            self._loop = None
            print(
                f"Dashboard did not bind {self.config.host}:{self.config.port} "
                f"(likely orphan server on that port). Script will continue; "
                f"metrics still go to the DB, just no live web UI."
            )
            print(
                f"  To free the port: "
                f"ss -ltnp 'sport = :{self.config.port}'   # find PID"
            )
            print(
                f"                    kill <PID>"
                f"                            # or: fuser -k {self.config.port}/tcp"
            )
            print(
                f"  Or pick another port: "
                f"OPENOPTICS_DASHBOARD_PORT=8002 python3 your_script.py"
            )

    def _stop_web(self) -> None:
        if self._server is None or self._loop is None:
            return
        self._server.should_exit = True
        # Let the loop notice, then join the thread.
        if self._loop_thread is not None:
            self._loop_thread.join(timeout=5.0)
        self._server = None
        self._loop = None
        self._loop_thread = None


class NullDashboard:
    """No-op dashboard used when ``use_webserver=False``.

    Exposes the same surface as :class:`DashboardService` so callers
    (``BaseNetwork``, ``OpticalCLI``) never need to check whether the
    dashboard is active.
    """

    def begin_epoch(self, seed=None): return None
    def update_topology(self, slice_to_topo): return None
    def register_collector(self, collector): return None
    def register_event_source(self, source): return None
    def start(self): return None
    def stop(self): return None
