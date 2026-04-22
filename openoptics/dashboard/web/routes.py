# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# Author: Yiming Lei (ylei@mpi-inf.mpg.de)
#
# License: Creative Commons NC BY SA 4.0
# https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en
"""HTTP routes: page shell + JSON API."""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from ..storage.repository import Repository

router = APIRouter()


def _repo(request: Request) -> Repository:
    return request.app.state.repo


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "dashboard.html")


@router.get("/api/metric_types")
def api_metric_types(request: Request):
    return [
        {
            "metric_type": m.metric_type,
            "display_name": m.display_name,
            "unit": m.unit,
            "chart_kind": m.chart_kind,
            "sort_order": m.sort_order,
        }
        for m in _repo(request).list_metric_types()
    ]


@router.get("/api/epochs")
def api_epochs(request: Request):
    return [
        {
            "id": e.id,
            "display_name": e.display_name,
            "created_at": e.created_at,
            "topo_image_url": e.topo_image_url,
        }
        for e in _repo(request).list_epochs()
    ]


@router.get("/api/epochs/{epoch_id}")
def api_epoch(request: Request, epoch_id: int):
    e = _repo(request).get_epoch(epoch_id)
    if e is None:
        raise HTTPException(status_code=404, detail="epoch not found")
    return {
        "id": e.id,
        "display_name": e.display_name,
        "created_at": e.created_at,
        "topo_image_url": e.topo_image_url,
    }


@router.get("/api/epochs/{epoch_id}/metrics")
def api_epoch_metrics(
    request: Request,
    epoch_id: int,
    metric_type: Optional[str] = None,
    device: Optional[str] = None,
):
    """Return samples for an epoch, grouped by ``(metric_type, device, labels)``.

    Response shape::

        {
          "queue_depth": [
            {"device": "tor0", "labels": {"port": 0, "queue": 0},
             "series": [[timestep, value], ...]},
            ...
          ],
          ...
        }
    """
    repo = _repo(request)
    if repo.get_epoch(epoch_id) is None:
        raise HTTPException(status_code=404, detail="epoch not found")

    samples = repo.query_samples(epoch_id, metric_type=metric_type, device=device)
    grouped: Dict[str, Dict[tuple, dict]] = defaultdict(dict)

    for s in samples:
        labels_key = tuple(sorted(s.labels.items()))
        key = (s.device, labels_key)
        group = grouped[s.metric_type]
        if key not in group:
            group[key] = {
                "device": s.device,
                "labels": dict(s.labels),
                "series": [],
            }
        group[key]["series"].append([s.timestep, s.value])

    return {mt: list(series.values()) for mt, series in grouped.items()}


@router.get("/api/epochs/{epoch_id}/devices")
def api_epoch_devices(request: Request, epoch_id: int):
    return _repo(request).distinct_devices(epoch_id)
