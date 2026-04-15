# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# Author: Yiming Lei (ylei@mpi-inf.mpg.de)
#
# This software is licensed for non-commercial scientific research purposes only.
#
# License text: Creative Commons NC BY SA 4.0
# https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en

import os
import re
import socket
import sys
import tempfile
from pathlib import Path

import numpy as np

from mininet.net import Mininet
from mininet.topo import Topo
from mininet.link import TCLink
from mininet.log import debug, error, info
from mininet.moduledeps import pathCheck
from mininet.node import Host, Switch
from mininet.util import pmonitor

from openoptics.backends.base import BackendBase, SwitchHandle, TableEntry

# ---------------------------------------------------------------------------
# P4 switch / host implementations
# ---------------------------------------------------------------------------

# Copyright 2013-present Barefoot Networks, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

class P4Host(Host):
    def config(self, **params):
        r = super(Host, self).config(**params)

        self.defaultIntf().rename("eth0")

        for off in ["rx", "tx", "sg"]:
            cmd = "/sbin/ethtool --offload eth0 %s off" % off
            self.cmd(cmd)

        # disable IPv6
        self.cmd("sysctl -w net.ipv6.conf.all.disable_ipv6=1")
        self.cmd("sysctl -w net.ipv6.conf.default.disable_ipv6=1")
        self.cmd("sysctl -w net.ipv6.conf.lo.disable_ipv6=1")

        return r

    def describe(self):
        print("**********")
        print(self.name)
        print(
            "default interface: %s\t%s\t%s"
            % (
                self.defaultIntf().name,
                self.defaultIntf().IP(),
                self.defaultIntf().MAC(),
            )
        )
        print("**********")


class P4Switch(Switch):
    """P4 virtual switch"""

    device_id = 0

    def __init__(
        self,
        name,
        sw_path=None,
        json_path=None,
        thrift_port=None,
        pcap_dump=False,
        log_console=True,
        verbose=True,
        device_id=None,
        enable_debugger=True,
        tor_id=0,
        time_slice_duration_ms=0,
        guardband_ms=0,
        nb_time_slices=None,
        calendar_queue_mode=0,  # 0 is TIME_BASED, 1 is CONTROL_BASED
        **kwargs,
    ):
        Switch.__init__(self, name, **kwargs)
        assert sw_path
        assert json_path
        pathCheck(sw_path)
        if not os.path.isfile(json_path):
            error(f"Invalid JSON file: {json_path}.\n")
            exit(1)
        self.sw_path = sw_path
        self.json_path = json_path
        self.verbose = verbose
        logfile = "/tmp/p4s.{}.log".format(self.name)
        self.output = open(logfile, "w")
        self.thrift_port = thrift_port
        self.pcap_dump = pcap_dump
        self.enable_debugger = enable_debugger
        self.log_console = log_console
        self.tor_id = tor_id
        self.time_slice_duration_ms = time_slice_duration_ms
        self.guardband_ms = guardband_ms
        assert nb_time_slices is not None
        self.nb_time_slices = nb_time_slices
        self.calendar_queue_mode = calendar_queue_mode

        if device_id is not None:
            self.device_id = device_id
            P4Switch.device_id = max(P4Switch.device_id, device_id)
        else:
            self.device_id = P4Switch.device_id
            P4Switch.device_id += 1
        self.nanomsg = "ipc:///tmp/bm-{}-log.ipc".format(self.device_id)

    @classmethod
    def setup(cls):
        pass

    def check_switch_started(self, pid):
        """Poll the Thrift port until it accepts connections."""
        while True:
            if not os.path.exists(os.path.join("/proc", str(pid))):
                return False
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.settimeout(0.5)
                result = sock.connect_ex(("localhost", self.thrift_port))
            finally:
                sock.close()
            if result == 0:
                return True

    def start(self, controllers):
        "Start up a new P4 switch"
        info("Starting P4 switch {}.\n".format(self.name))
        args = [self.sw_path]
        for port, intf in self.intfs.items():
            if not intf.IP():
                args.extend(["-i", str(port) + "@" + intf.name])
        if self.pcap_dump:
            args.append("--pcap")
        if self.thrift_port:
            args.extend(["--thrift-port", str(self.thrift_port)])
        if self.nanomsg:
            args.extend(["--nanolog", self.nanomsg])
        args.extend(["--device-id", str(self.device_id)])
        P4Switch.device_id += 1
        args.append(self.json_path)
        if self.enable_debugger:
            args.append("--debugger")
        if self.log_console:
            args.append("--log-console")
        # Special options for OCS or ToR switches
        if self.name.startswith("tor") or self.name.startswith("ocs"):
            args.extend(["-- --nb-time-slices", str(self.nb_time_slices)])
            args.extend(["--time-slice-duration-ms", str(self.time_slice_duration_ms)])
        if self.name.startswith("tor"):
            args.extend(["--guardband-ms", str(self.guardband_ms)])
            args.extend(["--calendar-queue-mode", str(self.calendar_queue_mode)])
            args.extend(["--tor-id", str(self.tor_id)])

        logfile = "/tmp/p4s.{}.log".format(self.name)
        info(" ".join(args) + "\n")

        pid = None
        with tempfile.NamedTemporaryFile() as f:
            self.cmd("echo" + " ".join(args) + ">" + logfile)
            self.cmd(" ".join(args) + " >" + logfile + " 2>&1 & echo $! >> " + f.name)
            pid = int(f.read())
        debug("P4 switch {} PID is {}.\n".format(self.name, pid))
        if not self.check_switch_started(pid):
            error("P4 switch {} did not start correctly.\n".format(self.name))
            exit(1)
        info("P4 switch {} has been started.\n".format(self.name))

    def stop(self):
        "Terminate P4 switch."
        self.output.flush()
        self.cmd("kill %" + self.sw_path)
        self.cmd("wait")
        self.deleteIntfs()

    def attach(self, intf):
        "Connect a data port"
        assert 0

    def detach(self, intf):
        "Disconnect a data port"
        assert 0

    def switch_type(self):
        sw_name = os.path.basename(self.sw_path)
        if sw_name == "optical_switch":
            return "optical"
        elif sw_name == "tor_switch":
            return "tor"
        else:
            return "default"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_rtt_from_ping(node1, node2, interval=1, nb_pkt=10, timeout=1):
    """Ping node2 from node1 and return a list of RTT values (ms)."""
    rtt_re = re.compile(r"time=(\d+(?:\.\d+)?)\s+ms")
    packets_re = re.compile(
        r'(?P<transmitted>\d+) packets transmitted, (?P<received>\d+) received'
    )

    popens = {}
    rtts = []

    popens[node1] = node1.popen(
        f"ping -i {interval} -c{nb_pkt} -W {timeout} {node2.IP()}"
    )

    for host, line in pmonitor(popens):
        packets_match = packets_re.search(line)
        if packets_match:
            transmitted = int(packets_match['transmitted'])
            received = int(packets_match['received'])
            if received / transmitted < 1 / 2:
                print(f"Host: {host}: packet loss!")

        rtt_match = rtt_re.search(line)
        if rtt_match:
            rtt = int(float(rtt_match.group(1)))
            rtts.append(rtt)

    return rtts


# ---------------------------------------------------------------------------
# MininetBackend
# ---------------------------------------------------------------------------

class MininetBackend(BackendBase):
    """Mininet + BMv2 backend for OpenOptics."""

    _CLI_PATH = "/behavioral-model/targets/simple_switch/runtime_CLI"

    _BACKEND_DIR = Path(__file__).resolve().parent

    _DEFAULT_OCS_SW   = "/behavioral-model/targets/optical_switch/optical_switch"
    _DEFAULT_OCS_JSON = str(_BACKEND_DIR / "p4src/ocs/ocs.json")
    _DEFAULT_TOR_SW   = "/behavioral-model/targets/tor_switch/tor_switch"
    _DEFAULT_TOR_JSON = str(_BACKEND_DIR / "p4src/tor/tor.json")

    # Maps logical table names (used by Toolbox) to BMv2-qualified names for table_clear.
    _TABLE_CLEAR_MAP = {
        "ocs_schedule":              "MyIngress.ocs_schedule",
        "per_hop_routing":           "per_hop_routing",
        "add_source_routing_entries": "source_routing",
        "cal_port_slice_to_node":    "cal_port_slice_to_node",
    }

    @classmethod
    def accepted_kwargs(cls) -> set:
        return {"link_delay_ms"}

    def __init__(
        self,
        ocs_sw_path: str = _DEFAULT_OCS_SW,
        ocs_json_path: str = _DEFAULT_OCS_JSON,
        tor_sw_path: str = _DEFAULT_TOR_SW,
        tor_json_path: str = _DEFAULT_TOR_JSON,
    ):
        self._ocs_sw_path   = ocs_sw_path
        self._ocs_json_path = ocs_json_path
        self._tor_sw_path   = tor_sw_path
        self._tor_json_path = tor_json_path
        self._net: Mininet = None
        self._ip_to_tor: dict = {}
        self._tor_switches: list = []  # list[SwitchHandle]

    # ------------------------------------------------------------------
    # BackendBase interface
    # ------------------------------------------------------------------

    def setup(
        self,
        *,
        nb_node,
        nb_host_per_tor,
        nb_link,
        nb_time_slices,
        time_slice_duration_us,
        guardband_ms,
        tor_host_port,
        host_tor_port,
        tor_ocs_ports,
        calendar_queue_mode,
        link_delay_ms=0,
        ocs_tor_link_bw=1000,
        tor_host_link_bw=1000,
        **backend_kwargs,
    ) -> None:
        """Create the Mininet topology and start the network."""
        time_slice_duration_ms = time_slice_duration_us // 1000
        guardband_ms = guardband_ms + link_delay_ms
        os.system("mn -c > /dev/null 2>&1")
        print("Setting up Mininet network...")

        topo = Topo()
        thrift_port = 9090

        # OCS switch
        ocs = topo.addSwitch(
            "ocs",
            dpid="0",
            sw_path=self._ocs_sw_path,
            json_path=self._ocs_json_path,
            thrift_port=thrift_port,
            pcap_dump=False,
            nb_time_slices=nb_time_slices,
            time_slice_duration_ms=time_slice_duration_ms,
            cls=P4Switch,
        )
        thrift_port += 1
        print("Optical switch created.")

        for tor_id in range(nb_node):
            tor_switch = topo.addSwitch(
                f"tor{tor_id}",
                dpid=f"{tor_id + 1}",
                sw_path=self._tor_sw_path,
                json_path=self._tor_json_path,
                thrift_port=thrift_port,
                pcap_dump=False,
                tor_id=tor_id,
                nb_time_slices=nb_time_slices if calendar_queue_mode == 0 else nb_node,
                time_slice_duration_ms=time_slice_duration_ms,
                guardband_ms=guardband_ms,
                calendar_queue_mode=calendar_queue_mode,
                cls=P4Switch,
            )

            for link_id in range(nb_link):
                ocs_port = link_id * nb_node + tor_id
                topo.addLink(
                    node1=ocs,
                    node2=tor_switch,
                    port1=ocs_port,
                    port2=tor_ocs_ports[link_id],
                    delay=f"{link_delay_ms}ms",
                    bw=ocs_tor_link_bw,
                )
            thrift_port += 1

            for _ in range(nb_host_per_tor):
                ip = f"10.0.{tor_id}.1"
                mac = "00:aa:bb:00:00:%02x" % tor_id
                host = topo.addHost("h" + str(tor_id), ip=ip, mac=mac)
                topo.addLink(
                    node1=host,
                    node2=tor_switch,
                    port1=host_tor_port,
                    port2=tor_host_port,
                    bw=tor_host_link_bw,
                    loss=0,
                )
                self._ip_to_tor[ip] = tor_id

        print(f"{nb_node} ToR switches created.")
        print("Starting Mininet network...")

        self._net = Mininet(
            topo, host=P4Host, switch=P4Switch, controller=None, link=TCLink
        )
        self._net.staticArp()

        for node_id in range(nb_node):
            h = self._net.get(f"h{node_id}")
            ip = f"10.0.{node_id}.1"
            mac = "00:aa:bb:00:00:%02x" % node_id
            h.setARP(ip, mac)

        self._net.start()

        # Cache ToR switch handles
        for switch in self._net.switches:
            if switch.switch_type() == "tor":
                self._tor_switches.append(SwitchHandle(switch.name, switch.thrift_port))

    def get_switch(self, name: str) -> SwitchHandle:
        node = self._net.nameToNode[name]
        return SwitchHandle(node.name, node.thrift_port)

    def switch_exists(self, name: str) -> bool:
        return name in self._net.nameToNode

    def get_tor_switches(self) -> list:
        return self._tor_switches

    def get_ip_to_tor(self) -> dict:
        return self._ip_to_tor

    @staticmethod
    def _render_action_params(params: dict) -> str:
        """Render action parameters to a space-separated BMv2 CLI string.

        Source-routing entries store hops as ``params["hops"]`` — a list of
        ``(cur_node, send_ts, send_port)`` tuples that are flattened here.
        All other tables store scalar values and are rendered in insertion order.
        """
        if "hops" in params:
            return " ".join(
                f"{cur_node} {send_ts} {send_port}"
                for cur_node, send_ts, send_port in params["hops"]
            )
        return " ".join(str(v) for v in params.values())

    @staticmethod
    def _entries_to_cli_str(entries: list) -> str:
        """Convert a list of TableEntry objects to BMv2 runtime_CLI commands."""
        lines = []
        for e in entries:
            if e.is_default_action:
                lines.append(f"table_set_default {e.table} {e.action}")
            else:
                keys_str = " ".join(str(v) for v in e.match_keys.values())
                params_str = MininetBackend._render_action_params(e.action_params)
                if params_str:
                    lines.append(f"table_add {e.table} {e.action} {keys_str} => {params_str}")
                else:
                    lines.append(f"table_add {e.table} {e.action} {keys_str} => ")
        return "\n".join(lines) + ("\n" if lines else "")

    def load_table(
        self,
        switch_name: str,
        entries: list,
        print_flag: bool = False,
        save_flag: bool = False,
        save_name: str = "saved_commands",
    ) -> bool:
        switch = self._net.nameToNode[switch_name]
        table_commands = self._entries_to_cli_str(entries)

        if save_flag:
            with open(f"{save_name}.txt", "w") as fh:
                fh.write(table_commands)

        if not table_commands:
            return True
        if table_commands[-1] == "\n":
            table_commands = table_commands[:-1]

        rst = switch.cmd(
            f'echo "{table_commands}" | {self._CLI_PATH} --thrift-port {switch.thrift_port}'
        )

        if rst is not None and print_flag:
            print(rst)

        if "Error:" in rst:
            assert False, f"Error for {switch_name}!\n{rst}\n{table_commands}"

        if "DUPLICATE_ENTRY" in rst:
            assert False, f"DUPLICATE_ENTRY for {switch_name}!\n{rst}\n{table_commands}"

        return True

    def clear_table(
        self,
        switch_name: str,
        table: str,
        print_flag: bool = False,
    ) -> None:
        bm2_name = self._TABLE_CLEAR_MAP.get(table, table)
        switch = self._net.nameToNode[switch_name]
        rst = switch.cmd(
            f'echo "table_clear {bm2_name}" | {self._CLI_PATH} --thrift-port {switch.thrift_port}'
        )
        if print_flag and rst:
            print(rst)

    def stop(self) -> None:
        self._net.stop()

    def cleanup(self) -> None:
        os.system("mn -c > /dev/null 2>&1")

    # ------------------------------------------------------------------
    # CLI extensions
    # ------------------------------------------------------------------

    def get_cli_commands(self) -> dict:
        """Return Mininet-specific CLI commands."""
        net = self._net

        def _my_applications(cli, line):
            """Cluster-ping application: heavy intra-cluster, light inter-cluster."""
            print("Application running... (~5s)")
            packets_re = re.compile(
                r'(?P<transmitted>\d+) packets transmitted, (?P<received>\d+) received'
            )
            rtt_summary_re = re.compile(
                r'rtt min/avg/max/mdev = '
                r'(?P<min>[\d.]+)/(?P<avg>[\d.]+)/(?P<max>[\d.]+)/[\d.]+'
            )
            rtt_re = re.compile(r"time=(\d+)\s+ms")

            popens = {}
            hosts = net.hosts
            middle = len(hosts) // 2

            for id in range(middle):
                popens[hosts[id]] = hosts[id].popen(
                    f"ping -i 0.2 -c30 -W 5 {hosts[(id + 1) % middle].IP()}"
                )
                popens[hosts[id + middle]] = hosts[id + middle].popen(
                    f"ping -i 0.2 -c30 -W 5 {hosts[((id + 1) % middle) + middle].IP()}"
                )

            for id in range(middle):
                popens[hosts[id]] = hosts[id].popen(
                    f"ping -i 0.5 -c15 -W 5 {hosts[len(hosts) - 1 - id].IP()}"
                )
                popens[hosts[id]] = hosts[id].popen(
                    f"ping -i 0.5 -c15 -W 5 {hosts[(id + 2) % middle + middle].IP()}"
                )

            failure_flag = False
            rtts = []

            for host, line in pmonitor(popens):
                packets_match = packets_re.search(line)
                rtt_match = rtt_re.search(line)

                if packets_match:
                    transmitted = int(packets_match['transmitted'])
                    received = int(packets_match['received'])
                    if received / transmitted < 1 / 2:
                        print(f"Host: {host}: packet loss!")
                        failure_flag = True

                if rtt_match:
                    rtt = int(rtt_match.group(1))
                    rtts.append(rtt)

            if len(rtts) == 0:
                print("No packets received!")
                failure_flag = True

            return failure_flag, rtts

        def do_test_task7(cli, line):
            """Test Tutorial task 7: Clustering application in direct routing."""
            failure_flag, rtts = _my_applications(cli, line)

            if failure_flag:
                print("\033[91mFailed!\033[0m There is packet loss.")
                return

            avg_rtt = int(sum(rtts) / len(rtts))
            tail_rtt = int(np.percentile(rtts, 99))
            target_avg_rtt = int(tail_rtt * 0.5)
            target_tail_rtt = 128 * 10  # 10 time slices

            if avg_rtt > target_avg_rtt:
                print(
                    f"\033[91mFailed!\033[0m Average RTT is too large: {avg_rtt}ms. "
                    f"Target: {target_avg_rtt}ms. "
                    "Did you allocate more connections within groups than across groups?"
                )
                return

            if tail_rtt > target_tail_rtt:
                print(
                    f"\033[92mPASS!\033[0m Bonus \033[91mfailed.\033[0m "
                    f"Tail RTT is too high: {tail_rtt}ms. "
                    f"Try reducing it under {target_tail_rtt}ms"
                )
                return

            print(
                f"\033[92mPASS!\033[0m No packet loss. "
                f"Tail RTT: {tail_rtt}ms is under the target {target_tail_rtt}ms. "
                f"Average RTT: {avg_rtt}ms is under the target ({target_avg_rtt}ms)."
            )

        def do_test_task8(cli, line):
            """Test Tutorial task 8: Check packet loss and ping tail RTT."""
            failure_flag, rtts = _my_applications(cli, line)

            if failure_flag:
                print("\033[91mFailed!\033[0m There is packet loss.")
                return

            avg_rtt = int(sum(rtts) / len(rtts))
            tail_rtt = int(np.percentile(rtts, 99))
            print(
                f"\033[92mPASS!\033[0m No packet loss. "
                f"Tail RTT: {tail_rtt}ms. Average RTT: {avg_rtt}ms."
            )
            do_test_task8_bonus(cli, line)

        def do_test_task8_bonus(cli, line):
            """Test Tutorial task 8 bonus: h0-h5 tail RTT."""
            print("Bonus running... (~2s)")
            rtts = _get_rtt_from_ping(
                net.hosts[0], net.hosts[5], interval=0.1, nb_pkt=20, timeout=2
            )
            if len(rtts) == 0:
                print("Failed because of packet loss.")
                return
            tail_rtt = int(np.percentile(rtts, 99))
            print(f"Bonus: h0-h5's tail RTT: {tail_rtt}ms")

        def do_get_rtt_cdf(cli, line):
            """Measure all-pairs RTT and save to <network_name>.txt."""
            nb_node = len(net.hosts)
            rtts = []
            for node1 in range(nb_node):
                for node2 in range(nb_node):
                    if node1 == node2:
                        continue
                    rtts.extend(
                        _get_rtt_from_ping(
                            net.hosts[node1],
                            net.hosts[node2],
                            interval=cli.slice_duration_ms / 1100,
                            nb_pkt=cli.nb_time_slices * 1,
                            timeout=10,
                        )
                    )
            np.savetxt(cli.base_network.name + ".txt", rtts, fmt="%d")

        def do_pingall(cli, line):
            """Ping between all hosts."""
            net.pingAll()

        return {
            "test_task7": (do_test_task7, do_test_task7.__doc__),
            "test_task8": (do_test_task8, do_test_task8.__doc__),
            "test_task8_bonus": (do_test_task8_bonus, do_test_task8_bonus.__doc__),
            "get_rtt_cdf": (do_get_rtt_cdf, do_get_rtt_cdf.__doc__),
            "pingall": (do_pingall, do_pingall.__doc__),
        }

    def default_handler(self, line: str) -> bool:
        """Dispatch commands to Mininet nodes, e.g. ``h0 ping h1``.

        Node names in the command are substituted with their IPs (mirrors
        mininet.cli.CLI.default()). Long-running commands stream output live;
        Ctrl+C sends SIGINT to the command and then returns to the CLI.
        """
        words = line.split()
        if not words:
            return False
        first = words[0]
        if first in self._net.nameToNode:
            node = self._net.nameToNode[first]
            rest = line[len(first):].strip().split()
            # Substitute node names with IPs
            rest = [
                self._net[arg].defaultIntf().updateIP() or arg
                if arg in self._net else arg
                for arg in rest
            ]
            node.sendCmd(" ".join(rest))
            try:
                while node.waiting:
                    output = node.monitor(timeoutms=100)
                    if output:
                        print(output, end="", flush=True)
            except KeyboardInterrupt:
                node.sendInt()
                print(node.waitOutput())
            return True
        return False
