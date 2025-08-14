# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# Author: Yiming Lei (ylei@mpi-inf.mpg.de)
#
# This software is licensed for non-commercial scientific research purposes only.
#
# License text: Creative Commons NC BY SA 4.0
# https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en

import json
from channels.generic.websocket import AsyncWebsocketConsumer


class MetricConsumer(AsyncWebsocketConsumer):
    """
    A consumer that accepts WebSocket connections on the path /ws/metrics/
    """

    async def connect(self):
        self.group_name = "metric_updates_group"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        """
        Receive data from WebSocket
        """
        pass

    async def send_update_to_websocket(self, event):
        """
        Send new data to html via WebSocket. Triggered by model updates (models.py:new_metric)
        """
        data = event["data"]
        await self.send(text_data=json.dumps(data))
