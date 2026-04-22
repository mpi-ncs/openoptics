# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# Author: Yiming Lei (ylei@mpi-inf.mpg.de)
#
# License: Creative Commons NC BY SA 4.0
# https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en
"""Live WebSocket endpoint: subscribes to the broker, forwards events as JSON.

Optional ``?epoch_id=N`` query filters to events from one epoch so old
browser tabs looking at a historical epoch don't get spammed with metrics
from the current run.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict

from fastapi import WebSocket, WebSocketDisconnect

from ..broker import EventBroker
from ..events import MetricSample, TopologyUpdate

log = logging.getLogger(__name__)


def _serialise(event) -> dict:
    if isinstance(event, MetricSample):
        return {"kind": "metric", **asdict(event)}
    if isinstance(event, TopologyUpdate):
        return {"kind": "topology", **asdict(event)}
    return {"kind": "unknown"}


async def live_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    broker: EventBroker = websocket.app.state.broker

    epoch_filter = websocket.query_params.get("epoch_id")
    epoch_id = int(epoch_filter) if epoch_filter is not None else None

    with broker.subscribe() as queue:
        try:
            while True:
                event = await queue.get()
                if epoch_id is not None and getattr(event, "epoch_id", None) != epoch_id:
                    continue
                await websocket.send_json(_serialise(event))
        except WebSocketDisconnect:
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("ws live endpoint error")
            try:
                await websocket.close()
            except Exception:
                pass
