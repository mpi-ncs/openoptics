# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# Author: Yiming Lei (ylei@mpi-inf.mpg.de)
#
# License: Creative Commons NC BY SA 4.0
# https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en
"""FastAPI application factory for the dashboard web UI."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..broker import EventBroker
from ..config import DashboardConfig
from ..storage.repository import Repository
from . import routes, websocket

WEB_DIR = Path(__file__).parent
STATIC_DIR = WEB_DIR / "static"
TEMPLATES_DIR = WEB_DIR / "templates"


def create_app(
    config: DashboardConfig,
    repo: Repository,
    broker: EventBroker,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        broker.bind_loop(asyncio.get_running_loop())
        yield

    app = FastAPI(
        title="OpenOptics Dashboard",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    app.state.config = config
    app.state.repo = repo
    app.state.broker = broker
    app.state.templates = templates

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    config.media_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=str(config.media_dir)), name="media")

    app.include_router(routes.router)
    app.add_api_websocket_route("/ws/live", websocket.live_endpoint)

    return app
