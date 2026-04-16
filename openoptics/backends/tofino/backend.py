# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# Author: Yiming Lei (ylei@mpi-inf.mpg.de)
#
# This software is licensed for non-commercial scientific research purposes only.
#
# License text: Creative Commons NC BY SA 4.0
# https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en

"""Tofino hardware backend for OpenOptics.

Deployment is split between ``deploy_topo()`` and ``deploy_routing()``:

- **OCS switch** is deployed during ``deploy_topo()``.  The control machine
  generates OCS table entries as JSON, SCPs them alongside the
  ``emulated-ocs/`` source tree, and launches ``run.sh``
  which compiles the binary and runs ``setup_ocs.py`` to configure ports,
  multicast, and load OCS entries from JSON.

- **ToR switches** are deployed during ``deploy_routing()``.  Same pattern:
  JSON routing entries are generated, SCP'd, and ``setup_tor.py`` handles
  everything on the switch.

The control machine does **not** need the Tofino SDE.

Physical testbed assumptions
-----------------------------
- A dedicated Tofino2 switch runs the OCS P4 program.
- One or more separate Tofino2 switches each host one or more ToR P4 pipes.
- Switch IPs, SSH credentials, and SDE paths are in a TOML config file.

Usage::

    net = BaseNetwork(
        name="tofino_test",
        backend="Tofino",
        nb_node=8,
        nb_link=4,
        time_slice_duration_ms=50,
        config_file="/path/to/my_testbed.toml",
    )
"""

from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional

from openoptics.backends.base import BackendBase, SwitchHandle, TableEntry

logger = logging.getLogger(__name__)


class TofinoBackend(BackendBase):
    """SSH-based backend for the OpenOptics Tofino2 testbed.

    Table mapping
    ~~~~~~~~~~~~~
    ========================= =========================================
    Logical table (frontend)  Handling
    ========================= =========================================
    ``ocs_schedule``          → JSON → ``setup_ocs.py`` on OCS switch
    ``per_hop_routing``       → JSON → ``setup_tor.py`` on ToR switch
    ``ip_to_dst_node``        → ``ip_to_mac_tor{N}.json`` → ``setup_tor.py``
                              (populates the source-ToR IP→dst-MAC rewrite
                              tables ``tb_ipv4_to_dst_mac`` /
                              ``tb_ipv6_to_dst_mac``)
    ``arrive_at_dst``         Silently skipped (handled by setup_tor.py)
    ``verify_desired_node``   Silently skipped (handled by setup_tor.py)
    ``cal_port_slice_to_node`` Silently skipped (handled by setup_tor.py)
    ========================= =========================================
    """

    supports_device_manager = False

    @classmethod
    def accepted_kwargs(cls) -> set:
        return {
            "config_file",
            "remote_workdir",
            "skip_deploy",
            "build_p4",
            "tofino_repo",
        }

    def __init__(self):
        self._nb_node: int = 0
        self._nb_link: int = 0
        self._nb_time_slices: int = 0
        self._remote_workdir: str = "/tmp/openoptics"
        self._duration_us: int = 0
        self._skip_deploy: bool = False
        self._build_p4: Optional[bool] = None

        # Pipe IDs: tor_id → pipe_id
        self._tor_pipe_ids: Dict[int, int] = {}
        # Mapping tor_id → SSH connection key
        self._tor_to_ssh_key: Dict[int, str] = {}

        # IP → tor_id mapping
        self._ip_to_tor: Dict[str, int] = {}

        # SwitchHandle objects
        self._tor_handles: List[SwitchHandle] = []
        self._switch_handles: Dict[str, SwitchHandle] = {}

        # Config and deployer
        self._config: Optional[dict] = None
        self._deployer = None
        self._tofino_repo: Optional[Path] = None

        # Deployment state
        self._ocs_deployed: bool = False
        self._tors_deployed: bool = False
        self._ocs_future = None  # Future for async OCS deployment
        self._deploy_executor = None  # ThreadPoolExecutor for async deploys

        # Accumulated ToR entries for batch deployment
        self._pending_tor_entries: Dict[int, list] = {}
        # Accumulated ip_to_dst_node entries per ToR (for IP→dst-MAC rewrite).
        self._pending_ip_to_dst_node: Dict[int, list] = {}
        # Accumulated cal_port_slice_to_node entries per ToR.
        self._pending_cal_port: Dict[int, list] = {}

        # Port-to-next-node lookup: (slice_id, node, port) -> next_node
        # Built by gen_schedule() from the deployed topology.
        self._port_to_next: Dict[tuple, int] = {}

        # Server management IPs: tor_id -> mgmt_ip (for SSH access)
        self._tor_to_server_mgmt: Dict[int, str] = {}
        # Reverse of _ip_to_tor: tor_id -> data-plane IP
        self._tor_to_ip: Dict[int, str] = {}
        # Server NIC name: tor_id -> NIC interface name (e.g. "enp23s0f0np0")
        self._tor_to_server_nic: Dict[int, str] = {}

    # ── BackendBase implementation ─────────────────────────────────────────

    def setup(
        self,
        *,
        nb_node: int,
        nb_host_per_tor: int,
        nb_link: int,
        nb_time_slices: int,
        time_slice_duration_us: int,
        guardband_ms: int,
        tor_host_port: int,
        host_tor_port: int,
        tor_ocs_ports: list,
        calendar_queue_mode: int,
        config_file: Optional[str] = None,
        remote_workdir: str = "/tmp/openoptics",
        skip_deploy: bool = False,
        build_p4: Optional[bool] = None,
        tofino_repo: Optional[str] = None,
        **backend_kwargs,
    ) -> None:
        """Parse config and prepare for deployment.

        Actual switch deployment is deferred to ``load_table()`` calls:
        OCS is deployed on the first OCS load_table, ToR switches on the
        first ToR load_table.
        """
        self._nb_node = nb_node
        self._nb_link = nb_link
        self._nb_time_slices = nb_time_slices
        self._remote_workdir = remote_workdir
        self._skip_deploy = skip_deploy
        self._build_p4 = build_p4
        self._duration_us = int(time_slice_duration_us)

        # Resolve tofino_repo path — defaults to this directory which
        # contains emulated-ocs/ and openoptics-tor/ subdirectories.
        if tofino_repo:
            self._tofino_repo = Path(tofino_repo)
        else:
            self._tofino_repo = Path(__file__).parent

        # Load config
        self._config = self._load_config(config_file)
        config = self._config

        # Map each logical ToR to a Tofino pipeline (0–3) on its physical switch.
        # Each physical switch has 4 pipelines, so at most 4 ToRs per switch.
        # Example: tor_id 0 → pipe 1, tor_id 1 → pipe 3
        self._tor_pipe_ids = {}
        if config:
            for phys_sw in config.get("physical_switch", []):
                for tor_cfg in phys_sw.get("logical_tor", []):
                    if "pipe_id" not in tor_cfg:
                        raise ValueError(
                            f"Missing pipe_id for tor_id {tor_cfg['tor_id']} in config.toml."
                        )
                    self._tor_pipe_ids[tor_cfg["tor_id"]] = tor_cfg["pipe_id"]

        # Build tor_id → ssh_key mapping and populate ip_to_tor from config
        if config:
            seen_tor_ids = set()
            for phys_sw in config.get("physical_switch", []):
                logical_tors = phys_sw.get("logical_tor", [])
                tor_ids = [t["tor_id"] for t in logical_tors]

                # Validate tor_id uniqueness
                for tid in tor_ids:
                    if tid in seen_tor_ids:
                        raise ValueError(f"Duplicate tor_id {tid} across physical switches")
                    seen_tor_ids.add(tid)

                # Validate no port conflicts within the same physical switch
                all_ports = set()
                for tcfg in logical_tors:
                    ports = (
                        tcfg.get("ocs_ports", [])
                        + tcfg.get("server_ports", [])
                        + [tcfg.get("electrical_port", "")]
                    )
                    for p in ports:
                        if not p:
                            continue
                        if p in all_ports:
                            raise ValueError(
                                f"Port conflict: '{p}' used by multiple logical tors "
                                f"on physical switch '{phys_sw.get('name', '?')}'"
                            )
                        all_ports.add(p)

                # SSH key mapping
                if tor_ids:
                    ssh_key = f"tor{tor_ids[0]}"
                    for tid in tor_ids:
                        self._tor_to_ssh_key[tid] = ssh_key

                # ip_to_tor and server management IP mappings
                for tcfg in logical_tors:
                    ip = tcfg.get("host_ip")
                    tid = tcfg.get("tor_id")
                    if ip is not None and tid is not None:
                        self._ip_to_tor[ip] = tid
                        self._tor_to_ip[tid] = ip
                    mgmt_ip = tcfg.get("server_mgmt_ip")
                    if mgmt_ip is not None and tid is not None:
                        self._tor_to_server_mgmt[tid] = mgmt_ip
                    nic = tcfg.get("server_nic")
                    if nic is not None and tid is not None:
                        self._tor_to_server_nic[tid] = nic

        if not self._ip_to_tor:
            for i in range(nb_node):
                self._ip_to_tor[f"10.0.{i}.1"] = i

        # Build SwitchHandle objects
        self._switch_handles["ocs"] = SwitchHandle("ocs", 0)
        for i in range(nb_node):
            h = SwitchHandle(f"tor{i}", i)
            self._tor_handles.append(h)
            self._switch_handles[f"tor{i}"] = h

        # Create deployer (for SSH connections)
        if config:
            from openoptics.backends.tofino.deploy import TofinoDeployer
            self._deployer = TofinoDeployer(config, tofino_repo=self._tofino_repo)
            if self._build_p4 is not None:
                self._deployer._build_p4_flag = self._build_p4
            self._deployer._nb_time_slices = self._nb_time_slices
            self._deployer._nb_link = self._nb_link

        logger.info("Tofino backend setup complete (%d ToRs). "
                     "Deployment deferred to load_table().", nb_node)

    def get_switch(self, name: str) -> SwitchHandle:
        return self._switch_handles[name]

    def switch_exists(self, name: str) -> bool:
        return name in self._switch_handles

    def get_tor_switches(self) -> list:
        return list(self._tor_handles)

    def get_ip_to_tor(self) -> dict:
        return dict(self._ip_to_tor)

    # Tables handled by setup_tor.py at switch startup — silently skip
    _SILENTLY_SKIP = {
        "arrive_at_dst",
        "verify_desired_node",
    }

    _CAL_PORT_TABLE = "cal_port_slice_to_node"

    # Tables that are extracted out of the routing_entries stream and
    # converted into side JSON files (loaded by setup_tor.py in a separate step).
    _IP_TO_DST_NODE_TABLE = "ip_to_dst_node"

    def load_table(
        self,
        switch_name: str,
        entries: list,
        print_flag: bool = False,
        save_flag: bool = False,
        save_name: str = "saved_commands",
    ) -> bool:
        """Generate JSON entries and deploy the switch if needed."""
        if switch_name == "ocs":
            self._deploy_ocs_with_entries(entries)
        elif switch_name.startswith("tor"):
            tor_id = int(switch_name[3:])
            # Split entries by table type.
            routing_entries = []
            ip_to_dst_entries = []
            cal_port_entries = []
            for e in entries:
                if e.is_default_action:
                    continue
                if e.table in self._SILENTLY_SKIP:
                    continue
                if e.table == self._IP_TO_DST_NODE_TABLE:
                    ip_to_dst_entries.append(e)
                elif e.table == self._CAL_PORT_TABLE:
                    cal_port_entries.append(e)
                else:
                    routing_entries.append(e)

            if ip_to_dst_entries:
                self._pending_ip_to_dst_node[tor_id] = ip_to_dst_entries
            if cal_port_entries:
                self._pending_cal_port[tor_id] = cal_port_entries

            if routing_entries:
                self._pending_tor_entries[tor_id] = routing_entries
                # Check if all ToRs have entries — deploy when complete
                if len(self._pending_tor_entries) >= self._nb_node:
                    self._deploy_tors_with_entries()
        else:
            logger.warning("load_table: unknown switch '%s', skipping.", switch_name)
        return True

    def clear_table(
        self,
        switch_name: str,
        table: str,
        print_flag: bool = False,
    ) -> None:
        """No-op — tables are cleared by setup scripts at switch startup."""
        logger.debug("clear_table(%s, %s): no-op for Tofino backend.", switch_name, table)

    def stop(self) -> None:
        """Kill remote control-plane processes and close SSH connections."""
        if self._deployer is not None:
            try:
                self._deployer.stop_all()
            except Exception as exc:
                logger.warning("stop_all failed: %s", exc)
        logger.info("Tofino backend stopped.")

    def cleanup(self) -> None:
        pass

    # ── Server SSH connections ───────────────────────────────────────────

    def get_server_ssh(self, tor_id: int):
        """Get (or create) an SSH connection to a ToR's end-host server.

        Connects via the server's management IP (``server_mgmt_ip`` in config),
        not the data-plane IP (``host_ip``).

        Args:
            tor_id: Logical ToR ID whose server to connect to.

        Returns:
            A connected paramiko SSHClient.
        """
        if self._deployer is None:
            raise RuntimeError("No deployer available — set config_file or disable skip_deploy.")
        mgmt_ip = self._tor_to_server_mgmt.get(tor_id)
        if mgmt_ip is None:
            raise ValueError(f"No server_mgmt_ip configured for tor_id {tor_id}")
        return self._deployer.connect_server(mgmt_ip)

    def server_exec(self, tor_id: int, command: str) -> str:
        """Execute a command on a ToR's server and return stdout."""
        ssh = self.get_server_ssh(tor_id)
        _, stdout, stderr = ssh.exec_command(command, timeout=30)
        return stdout.read().decode()

    def _server_stream_interactive(self, tor_id: int, command: str) -> None:
        """Run *command* on ToR *tor_id*'s server, streaming stdout/stderr live.

        Mirrors the Mininet backend's ``h0 ping h1`` UX: output appears as it
        arrives and Ctrl+C sends SIGINT to the remote process, then returns to
        the OpenOptics CLI. Used only for interactive ``hN <cmd>`` dispatch;
        ``server_exec`` stays blocking for callers that need full output.
        """
        import sys
        import time

        ssh = self.get_server_ssh(tor_id)
        transport = ssh.get_transport()
        chan = transport.open_session()
        chan.get_pty()
        chan.exec_command(command)
        chan.settimeout(0.0)

        def _drain(stderr: bool = False) -> bool:
            ready = chan.recv_stderr_ready() if stderr else chan.recv_ready()
            if not ready:
                return False
            data = chan.recv_stderr(4096) if stderr else chan.recv(4096)
            if not data:
                return False
            stream = sys.stderr if stderr else sys.stdout
            stream.write(data.decode(errors="replace"))
            stream.flush()
            return True

        try:
            while True:
                got = _drain(False) | _drain(True)
                if chan.exit_status_ready() and not got:
                    while _drain(False) or _drain(True):
                        pass
                    break
                if not got:
                    time.sleep(0.05)
        except KeyboardInterrupt:
            try:
                chan.send("\x03")
            except Exception:
                pass
            deadline = time.time() + 2.0
            while time.time() < deadline:
                got = _drain(False) | _drain(True)
                if chan.exit_status_ready() and not got:
                    break
                if not got:
                    time.sleep(0.05)
            print()
        finally:
            try:
                chan.close()
            except Exception:
                pass

    def check_servers(self) -> dict:
        """Connect to all servers, ensure NICs are up, IPs are configured,
        and install dummy ARP entries so Linux can emit cross-ToR packets.

        For each tor with ``server_nic`` and ``host_ip`` in config:
        1. Bring the NIC up (``sudo ip link set <nic> up``)
        2. Check if ``host_ip`` is assigned to ``<nic>``; assign if not
        3. Install a dummy static ARP entry for every OTHER tor's data-plane IP,
           pointing to a fixed placeholder MAC (``de:ad:be:ef:de:ad``).  The
           actual IP→tor-MAC mapping now lives in the P4 program on the source
           ToR (``tb_ipv4_to_dst_mac`` / ``tb_ipv6_to_dst_mac``), which
           overwrites the dst MAC before routing — so the server doesn't need
           to know anything about testbed tor-id encoding.  The dummy ARP
           entry exists only because Linux refuses to emit the IP packet until
           ARP resolution completes.

        IMPORTANT — dummy MAC choice:
            The Tofino ingress parser does ``lookahead<pktgen_timer_header_t>``
            and selects on ``app_id`` (the LOW 4 bits of the FIRST byte of the
            packet, i.e. the high byte of the dst MAC).  app_ids 1-7 cause the
            parser to take the pktgen branch, which consumes the ethernet
            header as a pktgen_timer header — destroying the IPv4 header and
            making the packet undeliverable.  The placeholder MAC's first byte
            MUST therefore have its lower 4 bits ∉ {1..7}.  ``0xde`` (lower
            nibble = 14) is safe; ``0x02`` would NOT be (lower nibble = 2,
            collides with pktgen app_id 2).

        Returns:
            Dict of {tor_id: {"reachable": bool, "ip_configured": bool, ...}}
        """
        DUMMY_MAC = "de:ad:be:ef:de:ad"
        results = {}
        for host_ip, tor_id in sorted(self._ip_to_tor.items(), key=lambda x: x[1]):
            mgmt_ip = self._tor_to_server_mgmt.get(tor_id)
            nic = self._tor_to_server_nic.get(tor_id)
            result = {
                "tor_id": tor_id,
                "host_ip": host_ip,
                "mgmt_ip": mgmt_ip,
                "nic": nic,
                "reachable": False,
                "ip_configured": False,
                "error": None,
            }
            if mgmt_ip is None:
                result["error"] = "no server_mgmt_ip in config"
                results[tor_id] = result
                continue
            try:
                if nic:
                    # Bring NIC up
                    self.server_exec(tor_id, f"sudo ip link set {nic} up")
                    # Check if host_ip is on this NIC
                    output = self.server_exec(tor_id, f"ip addr show {nic}")
                    result["reachable"] = True
                    if host_ip in output:
                        result["ip_configured"] = True
                    else:
                        # Assign the IP
                        self.server_exec(tor_id, f"sudo ip addr add {host_ip}/24 dev {nic}")
                        # Verify
                        output = self.server_exec(tor_id, f"ip addr show {nic}")
                        result["ip_configured"] = host_ip in output
                        if result["ip_configured"]:
                            result["ip_added"] = True
                    result["ip_info"] = output.strip()

                    # Install dummy ARP entries for all other ToRs so Linux
                    # will actually emit the IP packet.  The source ToR's P4
                    # program rewrites the dst MAC to the magic tor-id-encoded
                    # value, so the MAC installed here is intentionally a
                    # placeholder and carries no topology information.
                    arp_added = []
                    for other_ip, other_tor in self._ip_to_tor.items():
                        if other_tor == tor_id:
                            continue
                        self.server_exec(tor_id,
                            f"sudo arp -s {other_ip} {DUMMY_MAC} 2>&1 || "
                            f"sudo ip neigh replace {other_ip} lladdr {DUMMY_MAC} dev {nic}")
                        arp_added.append(f"{other_ip}->{DUMMY_MAC}")
                    result["arp_entries"] = arp_added
                else:
                    # No NIC specified — just check all interfaces
                    output = self.server_exec(tor_id, "ip addr show | grep 'inet ' | grep -v 127.0.0.1")
                    result["reachable"] = True
                    result["ip_configured"] = host_ip in output
                    result["ip_info"] = output.strip()
            except Exception as exc:
                result["error"] = str(exc)
            results[tor_id] = result
        return results

    def get_cli_commands(self) -> dict:
        """Register Tofino-specific CLI commands."""
        def cmd_server_check(cli, line):
            """Check connectivity, ensure NICs are up and IPs are configured on all servers."""
            results = self.check_servers()
            for tor_id, r in results.items():
                status = "OK" if r["reachable"] else "UNREACHABLE"
                if r["error"]:
                    print(f"  ToR {tor_id} ({r['mgmt_ip']}): {status} — {r['error']}")
                else:
                    nic_info = f" on {r['nic']}" if r.get("nic") else ""
                    ip_status = "configured" if r["ip_configured"] else "MISSING"
                    if r.get("ip_added"):
                        ip_status = "added"
                    print(f"  ToR {tor_id} ({r['mgmt_ip']}): {status}, {r['host_ip']}{nic_info} {ip_status}")
                    if r.get("ip_info"):
                        for ln in r["ip_info"].split("\n"):
                            print(f"    {ln.strip()}")

        def cmd_server_exec(cli, line):
            """Run a command on a server. Usage: server_exec <tor_id> <command>"""
            parts = line.strip().split(None, 1)
            if len(parts) < 2:
                print("Usage: server_exec <tor_id> <command>")
                return
            try:
                tor_id = int(parts[0])
            except ValueError:
                print(f"Invalid tor_id: {parts[0]}")
                return
            try:
                output = self.server_exec(tor_id, parts[1])
                print(output, end="")
            except Exception as exc:
                print(f"Error: {exc}")

        def cmd_server_ping(cli, line):
            """Ping from one server to another's data-plane IP. Usage: server_ping <src_tor> <dst_tor> [count]"""
            parts = line.strip().split()
            if len(parts) < 2:
                print("Usage: server_ping <src_tor_id> <dst_tor_id> [count]")
                return
            try:
                src_tor = int(parts[0])
                dst_tor = int(parts[1])
            except ValueError:
                print("tor_id must be an integer")
                return
            count = parts[2] if len(parts) > 2 else "3"
            dst_ip = self._host_ip_for_tor(dst_tor)
            if dst_ip is None:
                print(f"No data-plane IP found for tor_id {dst_tor}")
                return
            try:
                print(f"Pinging {dst_ip} (ToR {dst_tor}) from ToR {src_tor} server...")
                output = self.server_exec(src_tor, f"ping -c {count} -W 2 {dst_ip}")
                print(output, end="")
            except Exception as exc:
                print(f"Error: {exc}")

        return {
            "server_check": (cmd_server_check, "Check connectivity to all servers"),
            "server_exec": (cmd_server_exec, "Run command on a server: server_exec <tor_id> <cmd>"),
            "server_ping": (cmd_server_ping, "Ping between servers: server_ping <src_tor> <dst_tor> [count]"),
        }

    def _parse_host_id(self, name: str):
        """Parse 'h0' or '0' to an integer tor_id, or return None."""
        try:
            if name.startswith("h") and len(name) > 1:
                return int(name[1:])
            return int(name)
        except (ValueError, IndexError):
            return None

    def _host_ip_for_tor(self, tor_id: int):
        """Return the data-plane IP for a tor_id, or None."""
        return self._tor_to_ip.get(tor_id)

    def default_handler(self, line: str) -> bool:
        """Handle ``h0 ping h1`` style commands via server SSH.

        - ``h0`` alone opens an interactive shell on server 0.
        - ``h0 <cmd>`` runs <cmd> on server 0, substituting hN with data-plane IPs.
        - Returns False if the line doesn't start with a known host name.
        """
        words = line.split()
        if not words:
            return False

        src_id = self._parse_host_id(words[0])
        if src_id is None or src_id not in self._tor_to_server_mgmt:
            return False

        if len(words) == 1:
            # Interactive shell on the server
            mgmt_ip = self._tor_to_server_mgmt[src_id]
            print(f"Opening shell on h{src_id} ({mgmt_ip})...")
            print("Type 'exit' to return to OpenOptics CLI.")
            try:
                ssh = self.get_server_ssh(src_id)
                chan = ssh.invoke_shell()
                chan.settimeout(0.1)
                import sys, select
                while True:
                    # Read from remote
                    try:
                        data = chan.recv(4096)
                        if not data:
                            break
                        sys.stdout.write(data.decode(errors="replace"))
                        sys.stdout.flush()
                    except Exception:
                        pass
                    # Read from local stdin
                    if select.select([sys.stdin], [], [], 0.1)[0]:
                        user_input = sys.stdin.readline()
                        if not user_input:
                            break
                        chan.send(user_input)
                        if user_input.strip() == "exit":
                            break
                chan.close()
            except Exception as exc:
                print(f"Shell error: {exc}")
            return True

        # Command mode: substitute hN with data-plane IPs
        rest = words[1:]
        resolved = []
        for arg in rest:
            tid = self._parse_host_id(arg)
            if tid is not None:
                ip = self._host_ip_for_tor(tid)
                if ip:
                    resolved.append(ip)
                    continue
            resolved.append(arg)

        cmd_str = " ".join(resolved)
        try:
            self._server_stream_interactive(src_id, cmd_str)
        except Exception as exc:
            print(f"Error: {exc}")
        return True

    # ── OCS deployment ────────────────────────────────────────────────────

    def _deploy_ocs_with_entries(self, entries: list) -> None:
        """Generate OCS JSON, write config, and start OCS deployment async.

        The actual SSH deployment runs in a background thread so that
        ToR entry generation and deployment can proceed in parallel.
        Call ``_wait_for_ocs()`` to block until OCS is ready.
        """
        if self._ocs_deployed:
            logger.info("OCS already deployed, skipping.")
            return
        if self._deployer is None or self._skip_deploy:
            logger.info("OCS deployment skipped (no config or skip_deploy).")
            self._ocs_deployed = True
            return

        # Generate JSON from TableEntry objects
        ocs_json = self._gen_ocs_json(entries)
        json_path = self._tofino_repo / "emulated-ocs" / "ocs_entries.json"
        with open(json_path, "w") as f:
            json.dump(ocs_json, f, indent=2)
        logger.info("Generated OCS JSON with %d entries.", len(ocs_json["entries"]))

        # Write runtime config for the remote setup script
        self._write_config(self._tofino_repo / "emulated-ocs" / "openoptics_config.json")

        # Ensure jump host is connected before spawning a thread so that
        # _jump_pkey is available and ssh_connect won't need a password prompt.
        self._deployer._ensure_jump_host()
        self._deploy_executor = ThreadPoolExecutor(max_workers=1)
        self._ocs_future = self._deploy_executor.submit(
            self._deployer.deploy_ocs,
            remote_workdir=self._remote_workdir,
        )
        logger.info("OCS deployment started asynchronously.")

    def _wait_for_ocs(self) -> None:
        """Block until the async OCS deployment completes."""
        if self._ocs_future is None:
            return
        self._ocs_future.result()  # raises if OCS deploy failed
        self._ocs_deployed = True
        self._ocs_future = None
        if self._deploy_executor is not None:
            self._deploy_executor.shutdown(wait=False)
            self._deploy_executor = None

    def _gen_ocs_json(self, entries: list) -> dict:
        """Convert TableEntry objects to OCS JSON format.

        Only includes entries for tors that have OCS port connections
        (i.e., tor_ocs_port_pairs defined in config).
        """
        # Tors with OCS connections (from config)
        connected_tors = set(self._tor_pipe_ids.keys()) if self._config else set(range(self._nb_node))

        json_entries = []
        for e in entries:
            if e.is_default_action:
                continue
            if e.table != "ocs_schedule":
                continue

            ingress_logical = e.match_keys["ingress_port"]
            slice_id = e.match_keys["slice_id"]
            egress_logical = e.action_params["egress_port"]

            ingress_tor = ingress_logical % self._nb_node
            egress_tor = egress_logical % self._nb_node

            # Skip entries for tors without physical OCS connections
            if ingress_tor not in connected_tors or egress_tor not in connected_tors:
                continue

            json_entries.append({
                "cur_slice": slice_id,
                "ingress_tor": ingress_tor,
                "ingress_port": ingress_logical // self._nb_node,
                "egress_tor": egress_tor,
                "egress_port": egress_logical // self._nb_node,
            })
        return {"entries": json_entries}

    # ── ToR deployment ────────────────────────────────────────────────────

    def _deploy_tors_with_entries(self) -> None:
        """Generate ToR JSON files, deploy all ToRs in parallel, wait for OCS."""
        if self._tors_deployed:
            logger.info("ToRs already deployed, skipping.")
            return
        if self._deployer is None or self._skip_deploy:
            logger.info("ToR deployment skipped (no config or skip_deploy).")
            self._tors_deployed = True
            return

        # Generate one JSON file per ToR
        for tor_id, entries in self._pending_tor_entries.items():
            pipe_id = self._tor_pipe_ids.get(tor_id, tor_id % 4)
            tor_json = self._gen_tor_json(tor_id, pipe_id, entries)

            json_path = self._tofino_repo / "openoptics-tor" / f"tor_entries_tor{tor_id}.json"
            with open(json_path, "w") as f:
                json.dump(tor_json, f, indent=2)
            logger.info("Generated ToR %d JSON with %d per-hop, %d source-routing, "
                        "%d node-to-port, %d ip-to-mac entries (pipe %d).",
                        tor_id,
                        len(tor_json["per_hop_routing_entries"]),
                        len(tor_json["source_routing_entries"]),
                        len(tor_json["node_to_port_slice_entries"]),
                        len(tor_json["ip_to_mac_entries"]),
                        pipe_id)

        # Write runtime config for the remote setup script
        self._write_config(self._tofino_repo / "openoptics-tor" / "openoptics_config.json")

        # Deploy all ToR switches in parallel
        self._deployer.deploy_tors(
            remote_workdir=self._remote_workdir,
        )
        self._tors_deployed = True
        self._pending_tor_entries.clear()
        self._pending_ip_to_dst_node.clear()
        self._pending_cal_port.clear()

        # Wait for async OCS deployment to finish
        self._wait_for_ocs()

    def _gen_tor_json(self, tor_id: int, pipe_id: int, entries: list) -> dict:
        """Convert TableEntry objects to ToR JSON format.

        Produces entry lists consumed by setup_tor.py:
          - "per_hop_routing_entries"      → time_flow_table_per_hop
          - "source_routing_entries"       → time_flow_table_source
          - "node_to_port_slice_entries"   → cal_port_slice_to_node
        """
        per_hop_json = []
        sr_json_entries = []
        for e in entries:
            if e.is_default_action:
                continue
            if e.table == "per_hop_routing":
                dst = e.match_keys["dst"]
                cur_slice = e.match_keys["arrival_ts"]
                slot = e.action_params["send_ts"]
                port = e.action_params["send_port"]
                dst_group = dst + 0x10

                next_node = self._port_to_next.get((slot, tor_id, port))
                next_tor = (next_node + 0x10) if next_node is not None else dst_group

                per_hop_json.append({
                    "cur_slice": cur_slice,
                    "dst_group": dst_group,
                    "port": port,
                    "slot": slot,
                    "next_tor": next_tor,
                    "alternate_port": port,
                    "alternate_slot": slot,
                    "alternate_next_tor": next_tor,
                })
            elif e.table == "add_source_routing_entries":
                dst = e.match_keys["dst"]
                cur_slice = e.match_keys["arrival_ts"]
                hops = e.action_params["hops"]  # list of (cur_node, send_ts, send_port)
                dst_group = dst + 0x10

                if len(hops) > 2:
                    raise ValueError(
                        f"Tofino backend only supports source-routed paths of "
                        f"up to 2 hops, got {len(hops)} hops for ToR {tor_id} "
                        f"(cur_slice={cur_slice}, dst={dst}). Use "
                        f"routing_hoho(..., max_hop=2) or switch to "
                        f"routing_mode='Per-hop'."
                    )

                hop_json = []
                for hop_idx, (hop_cur_node, hop_send_ts, hop_send_port) in enumerate(hops):
                    if hop_send_ts == 255 and hop_send_port == 255:
                        # Random-port sentinel: pass through as-is.
                        # P4 data plane uses Random<> to pick a port.
                        hop_json.append({
                            "cur_node": hop_cur_node,
                            "send_slice": 255,
                            "send_port": 255,
                            "next_tor": 0xff,
                        })
                    elif hop_send_ts == 255:
                        # Node-indexed sentinel (e.g., VLB second hop):
                        # hop_send_port holds dst_node_id.
                        # Try to resolve into concrete values if the
                        # preceding hop gives a known intermediate.
                        resolved = False
                        if hop_idx > 0:
                            prev_cur, prev_ts, prev_port = hops[hop_idx - 1]
                            if prev_ts != 255:
                                intermediate = self._port_to_next.get(
                                    (prev_ts, prev_cur, prev_port)
                                )
                                if intermediate is not None:
                                    for s in range(self._nb_time_slices):
                                        for p in range(self._nb_link):
                                            if self._port_to_next.get(
                                                (s, intermediate, p)
                                            ) == hop_send_port:
                                                hop_json.append({
                                                    "cur_node": intermediate,
                                                    "send_slice": s,
                                                    "send_port": p,
                                                    "next_tor": hop_send_port + 0x10,
                                                })
                                                resolved = True
                                                break
                                        if resolved:
                                            break
                        if not resolved:
                            # Can't resolve — pass sentinel for transit P4
                            # to handle via cal_port_slice_to_node.
                            hop_json.append({
                                "cur_node": hop_cur_node,
                                "send_slice": 255,
                                "send_port": hop_send_port,
                                "next_tor": hop_send_port + 0x10,
                            })
                    else:
                        # Concrete hop (hoho, direct, etc.)
                        next_node = self._port_to_next.get(
                            (hop_send_ts, hop_cur_node, hop_send_port)
                        )
                        hop_next_tor = (next_node + 0x10) if next_node is not None else dst_group
                        hop_json.append({
                            "cur_node": hop_cur_node,
                            "send_slice": hop_send_ts,
                            "send_port": hop_send_port,
                            "next_tor": hop_next_tor,
                        })

                sr_json_entries.append({
                    "cur_slice": cur_slice,
                    "dst_group": dst_group,
                    "hops": hop_json,
                })

        # Generate node-to-port-slice entries from _pending_cal_port
        node_to_port_json = []
        for cal_e in self._pending_cal_port.get(tor_id, []):
            dst_node = cal_e.match_keys["dst"]
            arrival_ts = cal_e.match_keys["arrival_ts"]
            send_port = cal_e.action_params["send_port"]
            send_ts = cal_e.action_params["send_ts"]
            next_node = self._port_to_next.get((send_ts, tor_id, send_port))
            next_tor = (next_node + 0x10) if next_node is not None else (dst_node + 0x10)
            node_to_port_json.append({
                "dst_node": dst_node,
                "arrival_ts": arrival_ts,
                "send_port": send_port,
                "send_slice": send_ts,
                "next_tor": next_tor,
            })

        return {
            "pipe_id": pipe_id,
            "per_hop_routing_entries": per_hop_json,
            "source_routing_entries": sr_json_entries,
            "node_to_port_slice_entries": node_to_port_json,
            "ip_to_mac_entries": self._gen_ip_to_mac_entries(tor_id),
        }

    def _gen_ip_to_mac_entries(self, tor_id: int) -> List[dict]:
        """Build the IP → dst-node entries embedded in the ToR JSON.

        The list is ToR-local: every *other* ToR's data-plane IP(s) paired
        with their destination tor_id.  setup_tor.py converts each entry into a
        ``tb_ipv4_to_dst_mac`` / ``tb_ipv6_to_dst_mac`` rule whose action sets
        hdr.ethernet.dst_addr = 0x10 + dst_node.

        Prefers entries provided by the frontend via ``ip_to_dst_node``
        (``openoptics/utils.py:tor_table_ip_to_dst``).  Falls back to
        synthesizing from ``self._ip_to_tor`` if the frontend didn't emit any.
        """
        entries: List[dict] = []
        seen: set = set()

        # Prefer explicit frontend-generated entries.
        for e in self._pending_ip_to_dst_node.get(tor_id, []):
            ip = e.match_keys.get("ip")
            dst_node = e.action_params.get("dst_node")
            if ip is None or dst_node is None:
                continue
            if dst_node == tor_id:
                # A ToR doesn't need to rewrite its own server's MAC — that
                # packet is handled by tb_check_to_server, not time_flow_table.
                continue
            if ip in seen:
                continue
            seen.add(ip)
            entries.append({"ip": ip, "dst_node": int(dst_node)})

        # Belt-and-braces: if the frontend emitted nothing, fall back to the
        # config-derived ip_to_tor map.
        if not entries:
            for ip, other_tor in self._ip_to_tor.items():
                if other_tor == tor_id:
                    continue
                if ip in seen:
                    continue
                seen.add(ip)
                entries.append({"ip": ip, "dst_node": int(other_tor)})

        return entries

    # ── Schedule generation ─────────────────────────────────────────────

    def gen_schedule(self, slice_to_topo) -> None:
        """Generate schedule.txt from the deployed topology.

        Converts ``slice_to_topo`` (Dict[slice_id → nx.DiGraph]) into the
        schedule matrix used by the remote setup scripts for queue management
        (AFC pause/resume, slice-to-rank, dst-to-rank).

        Format: rows = time slices, columns = tor_id * nb_link + port_id,
        values = destination tor_id (-1 if no connection).
        """
        nb_cols = self._nb_node * self._nb_link
        schedule = [[-1] * nb_cols for _ in range(self._nb_time_slices)]

        self._port_to_next.clear()
        for slice_id, graph in slice_to_topo.items():
            for node1, node2, attr in graph.edges(data=True):
                port1, port2 = attr["port1"], attr["port2"]
                schedule[slice_id][node1 * self._nb_link + port1] = node2
                schedule[slice_id][node2 * self._nb_link + port2] = node1
                self._port_to_next[(slice_id, node1, port1)] = node2
                self._port_to_next[(slice_id, node2, port2)] = node1

        # Validate: the Tofino AFC logic requires guardband slices (at least
        # one -1 per port column) so find_connection_windows() can parse the
        # schedule into (start, pause, dst) windows.  Topologies without
        # guardbands (e.g. opera(..., guardband=False)) will crash setup_tor.py.
        # Only validate tors that have physical OCS connections
        connected_tors = set(self._tor_pipe_ids.keys()) if self._tor_pipe_ids else set(range(self._nb_node))
        for node in connected_tors:
            for port in range(self._nb_link):
                col = node * self._nb_link + port
                column = [schedule[ts][col] for ts in range(self._nb_time_slices)]
                if -1 not in column:
                    raise ValueError(
                        f"Tofino backend requires guardband time slices, but "
                        f"node {node} port {port} has no guardband (-1) in the "
                        f"schedule.  Use guardband=True when generating the "
                        f"topology (e.g. opera(..., guardband=True))."
                    )

        for out_dir in ("emulated-ocs", "openoptics-tor"):
            schedule_path = self._tofino_repo / out_dir / "schedule.txt"
            with open(schedule_path, "w") as f:
                for row in schedule:
                    f.write("\t".join(str(v) for v in row) + "\n")
            logger.info("Generated schedule.txt at %s", schedule_path)

    # ── Config helpers ────────────────────────────────────────────────────

    def _write_config(self, json_path: Path, **extra) -> None:
        """Write runtime network parameters as JSON for remote setup scripts."""
        config_data = {
            "TOR_NUM": self._nb_node,
            "PORT_NUM": self._nb_link,
            "NB_TIME_SLICES": self._nb_time_slices,
            "SLICE_DURATION": self._duration_us,
        }
        config_data.update(extra)

        if self._config:
            # Bandwidth defaults
            bw = self._config.get("bandwidth", {})
            config_data["bandwidth"] = {
                "uplink_gbps": bw.get("uplink_gbps", 100),
                "uplink_fec": bw.get("uplink_fec", "NONE"),
                "electrical_gbps": bw.get("electrical_gbps", 100),
                "electrical_fec": bw.get("electrical_fec", "NONE"),
                "server_gbps": bw.get("server_gbps", 100),
                "server_fec": bw.get("server_fec", "NONE"),
            }

            # Physical switches (name → tor_ids) for hostname lookup
            physical_switches = []
            all_tors = []
            ocs_fp_layout = []  # [[tor_id, port_idx, "ocs_cage/lane"], ...]
            for phys_sw in self._config.get("physical_switch", []):
                logical_tors = phys_sw.get("logical_tor", [])
                tor_ids = [t["tor_id"] for t in logical_tors]
                physical_switches.append({
                    "name": phys_sw.get("name", ""),
                    "tor_ids": tor_ids,
                })

                for tcfg in logical_tors:
                    tid = tcfg["tor_id"]
                    if tid not in self._tor_pipe_ids:
                        raise ValueError(
                            f"tor_id {tid} has no pipe_id mapping. "
                            f"Add pipe_id to [[physical_switch.logical_tor]] in config.toml."
                        )

                    # Derive ocs_ports (ToR side) from tor_ocs_port_pairs
                    port_pairs = tcfg.get("tor_ocs_port_pairs")
                    if port_pairs is None:
                        raise ValueError(
                            f"Missing tor_ocs_port_pairs for tor_id {tid}. "
                            f'Example: tor_ocs_port_pairs = [["7/0", "7/0"]]'
                        )
                    ocs_ports = [pair[0] for pair in port_pairs]

                    # Build OCS-side layout entries: [tor_id, port_idx, ocs_cage]
                    for port_idx, pair in enumerate(port_pairs):
                        ocs_fp_layout.append([tid, port_idx, pair[1]])

                    tor_entry = {
                        "tor_id": tid,
                        "pipe_id": self._tor_pipe_ids[tid],
                        "physical_switch": tcfg.get("physical_switch", ""),
                        "ocs_ports": ocs_ports,
                    }
                    # Optional fields — not all logical tors have servers or electrical links
                    for key in ("server_ports", "electrical_port", "host_ip", "server_nic"):
                        if key in tcfg:
                            tor_entry[key] = tcfg[key]
                    if "server_mac" in tcfg:
                        tor_entry["server_mac"] = self._mac_str_to_int(tcfg["server_mac"])
                    for fec_key in ("server_fec", "uplink_fec", "electrical_fec"):
                        if fec_key in tcfg:
                            tor_entry[fec_key] = tcfg[fec_key]
                    all_tors.append(tor_entry)

            config_data["physical_switches"] = physical_switches
            config_data["tors"] = all_tors
            config_data["ocs_fp_layout"] = ocs_fp_layout

        with open(json_path, "w") as f:
            json.dump(config_data, f, indent=2)
        logger.info("Wrote runtime config to %s", json_path)

    @staticmethod
    def _mac_str_to_int(mac_str: str) -> int:
        """Convert 'e8:eb:d3:ed:c5:ee' to integer."""
        return int(mac_str.replace(":", ""), 16)

    @staticmethod
    def _load_config(config_file: Optional[str]) -> dict:
        """Load and return the TOML config dict.

        Raises:
            ValueError: if config_file is None.
            FileNotFoundError: if the given path does not exist.
        """
        if config_file is None:
            raise ValueError(
                "Tofino backend requires a config_file. "
                "Pass config_file=... to TofinoBackend(...) pointing at a TOML "
                "config (e.g. openoptics-tofino.toml, generated by "
                "`openoptics-gen-config`)."
            )
        if not os.path.exists(config_file):
            raise FileNotFoundError(
                f"Tofino config file not found at '{config_file}'."
            )
        try:
            import tomllib
        except ImportError:
            try:
                import tomli as tomllib
            except ImportError:
                raise ImportError(
                    "A TOML parser is required to read the Tofino config file. "
                    "On Python < 3.11, install tomli: pip install tomli"
                )
        with open(config_file, "rb") as fh:
            return tomllib.load(fh)
