# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# Author: Yiming Lei (ylei@mpi-inf.mpg.de)
#
# This software is licensed for non-commercial scientific research purposes only.
#
# License text: Creative Commons NC BY SA 4.0
# https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en

from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


class Epochs(models.Model):
    display_name = models.CharField(max_length=100)
    topo_image = models.ImageField(upload_to="topos/")


class UniformMetrics(models.Model):
    device_name = models.CharField(max_length=100)
    label = models.CharField(max_length=100)  # (port,queue) or tor name
    depth = models.IntegerField()
    loss_ctr = models.FloatField()
    timestep = models.IntegerField()
    epoch = models.ForeignKey(Epochs, on_delete=models.CASCADE, related_name="metrics")


@receiver(post_save, sender=Epochs)
def new_topo(sender, instance, created, **kwargs):
    channel_layer = get_channel_layer()

    payload = {"type": "topo", "topo_image": instance.topo_image.url}

    async_to_sync(channel_layer.group_send)(
        "metric_updates_group", {"type": "send_update_to_websocket", "data": payload}
    )


# After saving DeviceMetrics, this functions is called to send data to websocket
@receiver(post_save, sender=UniformMetrics)
def new_metric(sender, instance, created, **kwargs):
    if not created:
        return  # Only send on new insertions

    channel_layer = get_channel_layer()

    payload = {
        "type": "metric",
        "device_name": instance.device_name,
        "label": instance.label,
        "depth": instance.depth,
        "timestep": instance.timestep,
        "loss_ctr": instance.loss_ctr,
        "epoch": instance.epoch.id,
    }

    async_to_sync(channel_layer.group_send)(
        "metric_updates_group", {"type": "send_update_to_websocket", "data": payload}
    )
