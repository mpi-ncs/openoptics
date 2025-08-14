# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# Author: Yiming Lei (ylei@mpi-inf.mpg.de)
#
# This software is licensed for non-commercial scientific research purposes only.
#
# License text: Creative Commons NC BY SA 4.0
# https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en

from django.shortcuts import render
from dashboardapp.models import Epochs, UniformMetrics
from django.utils.safestring import mark_safe

import json
from collections import defaultdict


def render_dashboard(request):
    """
    View is a single time execution. It renders old data into a dashboard if the showing epoch is old.
    Following data update is handled by websocket and consumers.py
    """
    epoch_id = request.GET.get("epoch_id", None)
    if epoch_id is None:
        showing_epoch = Epochs.objects.order_by("id").last()
    else:
        showing_epoch = Epochs.objects.filter(id=epoch_id).first()

    metric_data = UniformMetrics.objects.filter(epoch=showing_epoch).order_by(
        "timestep"
    )
    time_steps = list(metric_data.values_list("timestep", flat=True).distinct())

    devices = sorted(
        list(UniformMetrics.objects.values_list("device_name", flat=True).distinct())
    )

    metrics = [field.name for field in UniformMetrics._meta.get_fields()]
    excluded_metrics = {"device_name", "id", "label", "timestep", "epoch"}
    metrics = [field for field in metrics if field not in excluded_metrics]

    if showing_epoch is not None:
        topo_img_url = showing_epoch.topo_image.url
    else:
        topo_img_url = ""

    depth = defaultdict(lambda: defaultdict(list))
    loss_ctr = defaultdict(lambda: defaultdict(list))
    for m in metric_data:
        depth[m.device_name][m.label].append((m.timestep, m.depth))
        loss_ctr[m.device_name][m.label].append((m.timestep, m.loss_ctr))

    chart_depth_data = {}
    for device, label_data in depth.items():
        chart_depth_data[device] = []
        for label, data in label_data.items():
            chart_depth_data[device].append({"label": label, "data": data})

    chart_loss_data = {}
    for device, label_data in loss_ctr.items():
        chart_loss_data[device] = []
        for label, data in label_data.items():
            chart_loss_data[device].append({"label": label, "data": data})

    context = {
        "epochs": Epochs.objects.all(),
        "current_epoch": showing_epoch,
        "devices": devices,
        "metrics": metrics,
        "time_steps": time_steps,
        "depth_json": mark_safe(json.dumps(chart_depth_data)),
        "loss_ctr_json": mark_safe(json.dumps(chart_loss_data)),
        "topo_img_url": topo_img_url,
    }
    return render(request, "dashboard.html", context)
