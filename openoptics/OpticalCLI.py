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

from mininet.cli import CLI
from openoptics.DeviceManager import DeviceManager


class OpticalCLI(CLI):
    def __init__(
        self,
        optical_monitor: DeviceManager,
        mininet,
        stdin=sys.stdin,
        script=None,
        **kwargs,
    ):
        self.prompt = "OpenOptics> "
        self.optical_monitor = optical_monitor
        CLI.__init__(self, mininet, stdin, script, **kwargs)

    def get_switches_from_line(self, line):
        """
        Get switch names (e.g. tor0) from CLI
        """
        args = line.split()
        if len(args) == 0:
            switches = self.mn.switches
        else:
            switches = [switch for switch in self.mn.switches if switch.name in args]
        sw_names = [switch.name for switch in switches if switch.switch_type() == "tor"]
        if len(sw_names) == 0:
            print("No switches found. Format: get_num_queued_packets <switch_name>")
        return sw_names

    def do_get_network_metric(self, line):
        metric = self.optical_monitor.get_device_metric()
        for sw_name, metric in metric.items():
            print(sw_name)
            print(metric)
        print(metric)

    def do_get_num_queued_packets(self, line):
        sw_names = self.get_switches_from_line(line)
        metric = self.optical_monitor.get_device_metric()
        for sw_name in sw_names:
            print(f"{sw_name}: {metric[sw_name]['pq_depth']}")

    def do_get_packet_loss_ctr(self, line):
        sw_names = self.get_switches_from_line(line)
        metric = self.optical_monitor.get_device_metric()
        for sw_name in sw_names:
            print(f"{sw_name}: {metric[sw_name]['drop_ctr']}")
