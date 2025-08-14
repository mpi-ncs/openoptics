# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# Author: Yiming Lei (ylei@mpi-inf.mpg.de)
#
# This software is licensed for non-commercial scientific research purposes only.
#
# License text: Creative Commons NC BY SA 4.0
# https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en

import time
import threading
import sys
import os

from datetime import datetime
from io import BytesIO
import django
from django.core.files.base import ContentFile
from django.db.models.signals import post_save

from openoptics.OpticalTopo import draw_topo
from openoptics.DeviceManager import DeviceManager

sys.path.append(os.path.join(os.path.dirname(__file__), "dashboard"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")


class Dashboard:
    def __init__(
        self, slice_to_topo, optical_monitor: DeviceManager, nb_port=1, nb_queue=1
    ):
        self.nb_port = nb_port
        self.nb_queue = nb_queue

        # Initialize Django
        django.setup()

        # Can only import after above configuration
        from dashboardapp.models import Epochs, UniformMetrics

        # Store references as instance variables to avoid repeated imports
        self.Epochs = Epochs
        self.UniformMetrics = UniformMetrics

        self.running_db_thread = True

        self.optical_monitor = optical_monitor

        self.epoch_name = datetime.now().strftime("%d-%m-%Y")
        existing_epochs = self.Epochs.objects.filter(
            display_name__startswith=self.epoch_name
        )
        if existing_epochs.exists():
            existing_suffixes = [
                int(epoch.display_name[len(self.epoch_name) + 2 : -1])
                for epoch in existing_epochs
                if epoch.display_name[len(self.epoch_name) :].startswith(" (")
                and epoch.display_name.endswith(")")
            ]
            if existing_suffixes:
                next_suffix = max(existing_suffixes) + 1
            else:
                next_suffix = 1
            self.epoch_name = f"{self.epoch_name} ({next_suffix})"
        else:
            self.epoch_name += "(0)"

        self.current_epoch = self.Epochs(display_name=self.epoch_name)
        self.update_topo(slice_to_topo)

    def update_topo(self, slice_to_topo):
        """
        Update topology image
        """
        topology_fig = draw_topo(slice_to_topo)
        buffer = BytesIO()
        topology_fig.savefig(buffer, format="png", dpi=300, bbox_inches="tight")

        content_file = ContentFile(buffer.getvalue())
        self.current_epoch.topo_image.save(
            f"graph_slices_{self.epoch_name}.png", content_file
        )
        self.current_epoch.save()

    def start(self):
        """
        Start db update thread to store data into the db
        """
        time.sleep(1)  # wait until nodes set
        self.running_db_thread = True
        self.db_thread = threading.Thread(target=self.update_db)
        self.db_thread.start()

    def stop(self):
        """
        Stop db
        """
        self.running_db_thread = False
        self.db_thread.join()

    def update_db(self):
        """
        A thread updates db in an infinite loop
        """
        step_count = 0
        while self.running_db_thread:
            switches = self.optical_monitor.switches

            dict_device_metric = self.optical_monitor.get_device_metric()

            records = []

            for switch in switches:
                device_name = switch.name

                total_depth = 0
                total_loss = 0
                if len(dict_device_metric[switch.name]["pq_depth"].items()) == 0:
                    for port in range(self.nb_port):
                        for queue in range(self.nb_queue):
                            records.append(
                                self.UniformMetrics(
                                    device_name=device_name,
                                    label=f"({port},{queue})",
                                    depth=0,
                                    loss_ctr=0,
                                    timestep=step_count,
                                    epoch=self.current_epoch,
                                )
                            )
                else:
                    for (port, queue), metric_depth in dict_device_metric[switch.name][
                        "pq_depth"
                    ].items():
                        # print(f"Data from switch {switch.name}: key: {(port,queue)}, depth: {metric_depth}")
                        if metric_depth is None:
                            depth = 0
                        else:
                            depth = metric_depth

                        records.append(
                            self.UniformMetrics(
                                device_name=device_name,
                                label=f"({port},{queue})",
                                depth=depth,
                                loss_ctr=0,
                                timestep=step_count,
                                epoch=self.current_epoch,
                            )
                        )

                        total_depth += depth
                        total_loss += 0  # loss_ctr

                total_loss = dict_device_metric[switch.name]["drop_ctr"]

                records.append(
                    self.UniformMetrics(
                        device_name="network",
                        label=device_name,
                        depth=total_depth,
                        loss_ctr=total_loss,
                        timestep=step_count,
                        epoch=self.current_epoch,
                    )
                )

            instances = self.UniformMetrics.objects.bulk_create(records)
            for instance in instances:
                post_save.send(
                    sender=self.UniformMetrics,
                    instance=instance,
                    created=True,
                    raw=False,
                    using="default",
                )
            step_count += 1

            # Check more frequently to exit faster, while maintaining 1s udpate interval
            for _ in range(10):
                if not self.running_db_thread:
                    break
                time.sleep(0.1)
