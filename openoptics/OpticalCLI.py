# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# Author: Yiming Lei (ylei@mpi-inf.mpg.de)
#
# This software is licensed for non-commercial scientific research purposes only.
#
# License text: Creative Commons NC BY SA 4.0
# https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en

import cmd
import sys


class OpticalCLI(cmd.Cmd):
    """General-purpose CLI for OpenOptics.

    Backend-specific commands (e.g. Mininet host commands) are registered at
    runtime via ``backend.get_cli_commands()``.  Unrecognised commands are
    forwarded to ``backend.default_handler()`` so that, for example, the
    Mininet backend can dispatch ``h0 ping h1`` directly to a host.
    """

    intro = (
        "Welcome to OpenOptics CLI. Type 'help' for a list of commands.\n"
        "Type 'exit' or press Ctrl-D to quit."
    )

    def __init__(
        self,
        base_network,
        stdin=sys.stdin,
        script=None,
    ):
        self.prompt = "OpenOptics> "
        self.base_network = base_network
        self.device_manager = base_network.device_manager
        self.slice_duration_ms = base_network.time_slice_duration_ms
        self.nb_time_slices = base_network.nb_time_slices

        # Register backend-specific commands
        for cmd_name, (fn, doc) in base_network._backend.get_cli_commands().items():
            def _make_do(f, d):
                def do_cmd(line, _f=f, _cli=self):
                    return _f(_cli, line)
                do_cmd.__doc__ = d
                return do_cmd
            setattr(self, f"do_{cmd_name}", _make_do(fn, doc))

        cmd.Cmd.__init__(self, stdin=stdin)

        if script:
            self.use_rawinput = False
            self.stdin = open(script, "r")

        self.cmdloop()

    # ------------------------------------------------------------------
    # Switch helpers
    # ------------------------------------------------------------------

    def get_switches_from_line(self, line):
        """Return ToR switch names matching the space-separated names in *line*.

        If *line* is empty, return all ToR switch names.
        """
        tor_names = [sw.name for sw in self.base_network._backend.get_tor_switches()]
        args = line.split()
        if not args:
            return tor_names
        return [name for name in args if name in tor_names]

    def parse_node(self, s):
        """Parse input 'h0' or '0' to int 0."""
        try:
            if s[0] == "h" and len(s) > 1:
                return int(s[1:])
            else:
                return int(s)
        except ValueError:
            print(f"Invalid node name {s}")
            raise ValueError

    # ------------------------------------------------------------------
    # Topology commands
    # ------------------------------------------------------------------

    def do_connect(self, line):
        """Connect two nodes by reconfiguring OCS.

        Usage: connect [<time_slice>] <node1> <node2> [<port1> <port2>]
        e.g.   connect 0 1 2   or   connect 0 h1 h2
        """
        args = line.split()

        try:
            if len(args) not in [2, 3, 5]:
                raise ValueError

            if len(args) == 2:
                node1 = self.parse_node(args[0])
                node2 = self.parse_node(args[1])
                if not self.base_network.connect(time_slice=0, node1=node1, node2=node2):
                    print("Failed to connect")
                    return

            elif len(args) == 3:
                time_slice = int(args[0])
                if self.base_network.arch_mode == "TA" and time_slice != 0:
                    print("Time slice must be 0 for traffic-aware mode.")
                    return
                node1 = self.parse_node(args[1])
                node2 = self.parse_node(args[2])
                if not self.base_network.connect(time_slice=time_slice, node1=node1, node2=node2):
                    print("Failed to connect")
                    return

            elif len(args) == 5:
                time_slice = int(args[0])
                if self.base_network.arch_mode == "TA" and time_slice != 0:
                    print("Time slice must be 0 for traffic-aware mode.")
                    return
                node1 = self.parse_node(args[1])
                node2 = self.parse_node(args[2])
                port1 = int(args[3])
                port2 = int(args[4])
                if not self.base_network.connect(
                    time_slice=time_slice, node1=node1, node2=node2, port1=port1, port2=port2
                ):
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
        """Disconnect two nodes by reconfiguring OCS.

        Usage: disconnect [<time_slice>] <node1> <node2> [<port1> <port2>]
        e.g.   disconnect 0 1 2   or   disconnect 0 h1 h2
        """
        args = line.split()

        try:
            if len(args) not in [2, 3, 5]:
                raise ValueError

            if len(args) == 2:
                node1 = self.parse_node(args[0])
                node2 = self.parse_node(args[1])
                if not self.base_network.disconnect(time_slice=0, node1=node1, node2=node2):
                    print("Failed to disconnect.")
                    return

            elif len(args) == 3:
                time_slice = int(args[0])
                node1 = self.parse_node(args[1])
                node2 = self.parse_node(args[2])
                if not self.base_network.disconnect(time_slice=time_slice, node1=node1, node2=node2):
                    print("Failed to disconnect.")
                    return

            elif len(args) == 5:
                time_slice = int(args[0])
                node1 = self.parse_node(args[1])
                node2 = self.parse_node(args[2])
                port1 = int(args[3])
                port2 = int(args[4])
                if not self.base_network.disconnect(
                    time_slice=time_slice, node1=node1, node2=node2, port1=port1, port2=port2
                ):
                    print("Failed to disconnect.")
                    return

        except ValueError:
            print("Invalid input. Usage: disconnect [<time_slice>] <node1_id> <node2_id> [<port1> <port2>]")
            print("e.g. disconnect 0 1 2 or disconnect 0 h1 h2")
            return

        self.base_network.dashboard.update_topo(self.base_network.slice_to_topo)
        self.base_network.deploy_topo()
        self.base_network.activate_calendar_queue()

    # ------------------------------------------------------------------
    # Monitoring commands
    # ------------------------------------------------------------------

    def do_get_network_metric(self, line):
        """Print device metrics for all switches."""
        metric = self.device_manager.get_device_metric()
        for sw_name, sw_metric in metric.items():
            print(sw_name)
            print(sw_metric)

    def do_get_num_queued_packets(self, line):
        """Print queue depths for the given switches (or all ToRs if none specified)."""
        sw_names = self.get_switches_from_line(line)
        metric = self.device_manager.get_device_metric()
        for sw_name in sw_names:
            print(f"{sw_name}: {metric[sw_name]['pq_depth']}")

    def do_get_packet_loss_ctr(self, line):
        """Print packet-loss counters for the given switches (or all ToRs)."""
        sw_names = self.get_switches_from_line(line)
        metric = self.device_manager.get_device_metric()
        for sw_name in sw_names:
            print(f"{sw_name}: {metric[sw_name]['drop_ctr']}")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def do_exit(self, _line):
        """Exit OpenOptics CLI."""
        return True

    def do_EOF(self, _line):
        """Exit on Ctrl-D."""
        print()
        return True

    do_quit = do_exit

    # ------------------------------------------------------------------
    # Fallback: forward unrecognised commands to the backend
    # ------------------------------------------------------------------

    def default(self, line):
        if not self.base_network._backend.default_handler(line):
            print(f"Unknown command: {line!r}. Type 'help' for a list of commands.")
