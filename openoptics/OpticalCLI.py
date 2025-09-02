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
import re

import numpy as np

from mininet.cli import CLI
from openoptics.DeviceManager import DeviceManager
from mininet.util import pmonitor


class OpticalCLI(CLI):
    def __init__(
        self,
        base_network,
        stdin=sys.stdin,
        script=None,
        **kwargs,
    ):
        
        self.prompt = "OpenOptics> "
        self.base_network = base_network
        self.mn = base_network.mininet_net
        self.device_manager = base_network.device_manager
        CLI.__init__(self, self.mn, stdin, script, **kwargs)

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

    def parse_node(self, s):
        """Parse input 'h0' or '0' to int 0."""
        try:
            if s[0] == 'h' and len(s) > 1:
                return int(s[1:])
            else:
                return int(s)
        except ValueError:
            print(f"Invalid node name {s}")
            raise ValueError
    def do_connect(self, line):
        """
        Connect two nodes by reconfigure OCS
        """
        args = line.split()
        
        try:
            if len(args) not in [2,3,5]:
                raise ValueError
            
            if len(args) == 2:
                node1 = self.parse_node(args[0])
                node2 = self.parse_node(args[1])
                if not self.base_network.connect(time_slice=0,node1=node1,node2=node2):
                    print("Failed to connect")
                    return
                
            elif len(args) == 3:
                time_slice = int(args[0])
                node1 = self.parse_node(args[1])
                node2 = self.parse_node(args[2])
                if not self.base_network.connect(time_slice=time_slice,node1=node1,node2=node2):
                    print("Failed to connect")
                    return

            elif len(args) == 5:
                time_slice = int(args[0])
                node1 = self.parse_node(args[1])
                node2 = self.parse_node(args[2])
                port1 = int(args[3])
                port2 = int(args[4])
                if not self.base_network.connect(time_slice=time_slice,node1=node1,node2=node2,port1=port1,port2=port2):
                    print("Failed to connect")
                    return
                    
        except ValueError:
            print("Invalid input. Format: connect [<time_slice>] <node1_id> <node2_id> [<port1> <port2>]")
            print("e.g. connect 0 1 2 or connect 0 h1 h2")
            return
            
        self.base_network.dashboard.update_topo(self.base_network.slice_to_topo)
        self.base_network.deploy_topo()
        self.base_network.activate_calendar_queue()
        
    def do_disconnect(self, line):
        """
        Disconnect two nodes by reconfigure OCS
        """
        args = line.split()
        
        try:
            if len(args) not in [2,3,5]:
                raise ValueError
            
            if len(args) == 2:
                node1 = self.parse_node(args[0])
                node2 = self.parse_node(args[1])
                if not self.base_network.disconnect(time_slice=0,node1=node1,node2=node2):
                    print("Failed to disconnect.")
                    return
                
            elif len(args) == 3:
                time_slice = int(args[0])
                node1 = self.parse_node(args[1])
                node2 = self.parse_node(args[2])
                if not self.base_network.disconnect(time_slice=time_slice,node1=node1,node2=node2):
                    print("Failed to disconnect.")
                    return

            elif len(args) == 5:
                time_slice = int(args[0])
                node1 = self.parse_node(args[1])
                node2 = self.parse_node(args[2])
                port1 = int(args[3])
                port2 = int(args[4])
                if not self.base_network.disconnect(time_slice=time_slice,node1=node1,node2=node2,port1=port1,port2=port2):
                    print("Failed to disconnect.")
                    return

        except ValueError:
            print("Invalid input. Usage: disconnect [<time_slice>] <node1_id> <node2_id> [<port1> <port2>]")
            print("e.g. disconnect 0 1 2 or disconnect 0 h1 h2")
            return
        
        self.base_network.dashboard.update_topo(self.base_network.slice_to_topo)
        self.base_network.deploy_topo()
        self.base_network.activate_calendar_queue()
    def do_get_network_metric(self, line):
        metric = self.device_manager.get_device_metric()
        for sw_name, metric in metric.items():
            print(sw_name)
            print(metric)
        print(metric)

    def do_get_num_queued_packets(self, line):
        sw_names = self.get_switches_from_line(line)
        metric = self.device_manager.get_device_metric()
        for sw_name in sw_names:
            print(f"{sw_name}: {metric[sw_name]['pq_depth']}")

    def do_get_packet_loss_ctr(self, line):
        sw_names = self.get_switches_from_line(line)
        metric = self.device_manager.get_device_metric()
        for sw_name in sw_names:
            print(f"{sw_name}: {metric[sw_name]['drop_ctr']}")
    def my_applications (self, line):
        """This application creates cluster pinging. It divides the network into two clusters
        ping within clusters a lot and ping between clusters little."""

        print("Application running... (~5s)")
        packets_re = re.compile(
            r'(?P<transmitted>\d+) packets transmitted, (?P<received>\d+) received'
        )

        # Regex for the RTT stats
        rtt_summary_re = re.compile(
            r'rtt min/avg/max/mdev = '
            r'(?P<min>[\d.]+)/(?P<avg>[\d.]+)/(?P<max>[\d.]+)/[\d.]+'
        )

        rtt_re = re.compile(
            r"time=(\d+)\s+ms"
        )

        popens = {}
        hosts = self.mn.hosts
        middle = len(hosts) // 2

        # Internal traffic
        for id in range(middle):
            pass
            #print(f"Internal: {hosts[id]} ping {hosts[(id+1) % middle]}")
            #print(f"Internal: {hosts[id+middle]} ping {hosts[((id+1) % middle) + middle]}")
            popens[hosts[id]] = hosts[id].popen(f"ping -i 0.1 -c50 -W 5 {hosts[(id+1) % middle].IP()}")
            popens[hosts[id+middle]] = hosts[id+middle].popen(f"ping -i 0.1 -c50 -W 5 {hosts[((id+1) % middle) + middle].IP()}")

        # External traffic
        for id in range(middle):
            #print(f"External: {hosts[id]} ping {hosts[len(hosts)-1-id]}")
            #print(f"External: {hosts[id]} ping {hosts[(id+1) % middle + middle]}")
            popens[hosts[id]] = hosts[id].popen(f"ping -i 0.2 -c25 -W 5 {hosts[len(hosts)-1-id].IP()}")
            popens[hosts[id]] = hosts[id].popen(f"ping -i 0.2 -c25 -W 5 {hosts[(id+2) % middle + middle].IP()}")
        
        failure_flag = False
        rtts = []

        for host, line in pmonitor(popens):
            #print(f"{host}: {line}")
                    
            # Extract data
            packets_match = packets_re.search(line)
            rtt_summary_match = rtt_summary_re.search(line)
            rtt_match = rtt_re.search(line)

            if packets_match: 
                #print("packets_match")
                transmitted = int(packets_match['transmitted'])
                received = int(packets_match['received'])
                #print(f"Host: {host}: {transmitted} transmitted, {received} received")
                if transmitted - received > 1: # There is chance for one packet loss
                    print(f"Host: {host}: packet loss!")
                    failure_flag = True

            if rtt_match:
                rtt = int(rtt_match.group(1))
                rtts.append(rtt)
        
        if len(rtts) == 0: # No packets received
            print("No packets received!")
            failure_flag = True

        return failure_flag, rtts
    def do_test_task7(self, line):
        """To test Tutorial task7. Clustering application in direct routing."""

        failure_flag, rtts = self.my_applications(line)

        if failure_flag:
            print("\033[91mFailed!\033[0m There is packet loss.")
            return
        
        avg_rtt = int(sum(rtts)/len(rtts))
        tail_rtt = int(np.percentile(rtts, 99))
        target_avg_rtt = int(tail_rtt * 0.5)
        target_tail_rtt =  64 * 10 # 64ms time slice, 8 nodes

        if tail_rtt > target_tail_rtt: 
            print(f"\033[91mFailed!\033[0m Tail RTT is too high: {tail_rtt}ms. Reduce it under {target_tail_rtt}ms") # 6+7
            return

        if avg_rtt > target_avg_rtt:
            print(f"\033[91mFailed!\033[0m Average RTT is too large: {avg_rtt}ms. Target: {target_avg_rtt}ms\
Did you allocate more connections within groups than across groups?")
            return
        
        print(f"\033[92mPASS!\033[0m No packet loss. Tail RTT: {tail_rtt}ms is under the target {target_tail_rtt}ms. Average RTT: {avg_rtt}ms is under the target ({target_avg_rtt}ms).")
    
    def do_test_task8(self, line):
        """To test Tutorial task8. Check packet loss and ping tail RTT between h0 and h5"""

        failure_flag, rtts = self.my_applications(line)

        if failure_flag:
            print("\033[91mFailed!\033[0m There is packet loss.")
            return
        
        avg_rtt = int(sum(rtts)/len(rtts))
        tail_rtt = int(np.percentile(rtts, 99))
        
        print(f"\033[92mPASS!\033[0m No packet loss. Tail RTT: {tail_rtt}ms. Average RTT: {avg_rtt}m.")
        self.do_test_task8_bonus(line)
    def do_test_task8_bonus(self, line):

        print("Bonus running... (~2s)")
        rtts = get_rtt_from_ping(self.mn.hosts[0], self.mn.hosts[5], interval=0.1, nb_pkt=20, timeout=2)
        if len(rtts) == 0: # No packets received
            print("Failed because of packet loss.")
            return
        tail_rtt = int(np.percentile(rtts, 99))
        print(f"Bonus: h0-h5's tail RTT: {tail_rtt}ms")

def get_rtt_from_ping(node1, node2, interval=1, nb_pkt=10, timeout=1):
    rtt_re = re.compile(
        r"time=(\d+)\s+ms"
    )

    packets_re = re.compile(
            r'(?P<transmitted>\d+) packets transmitted, (?P<received>\d+) received'
        )
    
    popens = {}
    rtts = []

    popens[node1] = node1.popen(f"ping -i {interval} -c{nb_pkt} -W {timeout} {node2.IP()}")

    for host, line in pmonitor(popens):
        #print(f"{host}: {line}")
        
        packets_match = packets_re.search(line)
        if packets_match: 
            transmitted = int(packets_match['transmitted'])
            received = int(packets_match['received'])
            if transmitted - received > 1: # There is chance for one packet loss
                print(f"Host: {host}: packet loss!")

        # Extract data
        rtt_match = rtt_re.search(line)
        if rtt_match:
            rtt = int(rtt_match.group(1))
            rtts.append(rtt)
    
    return rtts