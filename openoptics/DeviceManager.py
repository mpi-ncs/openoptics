# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# Author: Yiming Lei (ylei@mpi-inf.mpg.de)
#
# This software is licensed for non-commercial scientific research purposes only.
#
# License text: Creative Commons NC BY SA 4.0
# https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en

import sys

from openoptics.backends.base import BackendBase


class DeviceManager:
    """
    OpenOptics DeviceManager. Monitor and configure the network at runtime.
    """

    def __init__(self, backend: BackendBase, tor_ocs_ports, nb_queue):
        sys.path.insert(1, "../behavioral-model/targets/tor_switch")
        sys.path.insert(1, "../behavioral-model/tools")
        from tswitch_CLI import TorSwitchAPI
        import runtime_CLI

        self.switches = backend.get_tor_switches()

        self.switch_clients = {}  # switch name -> thrift client
        services = TorSwitchAPI.get_thrift_services()

        for sw in self.switches:
            switch_client = runtime_CLI.thrift_connect(
                "localhost", sw.thrift_port, services
            )[0]
            self.switch_clients[sw.name] = switch_client

        self.tor_ocs_ports = tor_ocs_ports
        self.nb_queue = nb_queue

    def get_device_metric(self) -> dict:
        """
        Get device metric (queue depth, loss rate, ...)

        Return:
            A dict with key [pq_depth] and [drop_ctr].
            Values of pq_depth is a dict with key (port, queue)
        """
        dict_device_metric = {}
        for sw_name, switch_client in self.switch_clients.items():
            try:
                device_metric = switch_client.get_device_metric()
                dict_device_metric[sw_name] = {
                    "pq_depth": {},
                    "drop_ctr": device_metric.drop_ctr,
                }

                for pq_metric in device_metric.port_queue_metrics:
                    dict_device_metric[sw_name]["pq_depth"].update(
                        {(pq_metric.port, pq_metric.queue): pq_metric.depth}
                    )
            except Exception:
                dict_device_metric[sw_name] = {"pq_depth": {}, "drop_ctr": 0}

        return dict_device_metric

    def set_active_queue(self, sw_name, active_qid):
        """
        Set the active queue for a specific switch.

        Args:
            sw_name: The name of the switch to configure
            active_qid: The ID of the queue to set as active
        """
        try:
            self.switch_clients[sw_name].set_active_queue(active_qid)
        except Exception:
            pass
