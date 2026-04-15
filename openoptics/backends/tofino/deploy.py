# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# Author: Yiming Lei (ylei@mpi-inf.mpg.de)
#
# This software is licensed for non-commercial scientific research purposes only.
#
# License text: Creative Commons NC BY SA 4.0
# https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en

"""SSH-based deployment of Tofino P4 programs and control-plane scripts.

This module handles:
1. SSH into each Tofino switch (OCS and ToR switches separately).
2. Copying the deployment source tree to each switch via SCP.
3. Launching ``run.sh`` which compiles and starts the control-plane binary.
4. Waiting for the BFRt gRPC port to accept connections.

Usage::

    from openoptics.backends.tofino.deploy import TofinoDeployer

    deployer = TofinoDeployer(config, tofino_repo=Path("openoptics/backends/tofino"))
    deployer.deploy_ocs(remote_workdir="/tmp/openoptics")
    deployer.deploy_tors(remote_workdir="/tmp/openoptics")
    # ... run experiment ...
    deployer.stop_all()
"""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class TofinoDeployer:
    """SSH/SCP-based deployer for OpenOptics Tofino switches.

    Parameters
    ----------
    config:
        Parsed ``config.toml`` dict.
    tofino_repo:
        Absolute path to the directory
        that contains ``emulated-ocs/`` and ``openoptics-tor/``.
    """

    def __init__(self, config: dict, tofino_repo: Path) -> None:
        self._config = config
        self._tofino_repo = Path(tofino_repo)
        self._sde_path: str = config.get("sde", {}).get("path", "/home/p4/bf-sde-9.12.0")
        self._sde_install: str = config.get("sde", {}).get(
            "install", "/home/p4/bf-sde-9.12.0/install"
        )
        self._bfrt_port: int = config.get("bfrt", {}).get("port", 50052)
        self._bfrt_timeout: int = config.get("bfrt", {}).get("startup_timeout", 60)
        self._build_p4_flag: bool = config.get("sde", {}).get("build_p4", True)

        # Active SSH clients: {"ocs": client, "tor0": client, ...}
        self._ssh_clients: Dict[str, object] = {}

        # Shared SSH connection to the jump host (lazily opened, reused)
        self._jump_client = None
        # Private key fetched from the jump host for target switch auth
        self._jump_pkey = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def deploy_ocs(
        self,
        remote_workdir: str = "/tmp/openoptics",
    ) -> str:
        """Deploy and start the OCS switch.

        Copies ``emulated-ocs/`` to the switch, launches ``run.sh``, and
        waits for BFRt gRPC to become available.

        Returns the ``host:port`` gRPC address.
        """
        ocs_cfg = self._config["ocs_switch"]
        host = ocs_cfg["host"]
        logger.info("Deploying OCS to %s ...", host)

        ssh = self.ssh_connect(ocs_cfg)
        self._ssh_clients["ocs"] = ssh

        # Upload emulated-ocs/ directory
        local_dir = self._tofino_repo / "emulated-ocs"
        remote_dir = remote_workdir + "/emulated-ocs"
        self._upload_dir(ssh, local_dir, remote_dir)

        # Compile P4 on the switch (blocking)
        self._build_p4(
            ssh, remote_workdir=remote_workdir,
            subdir="emulated-ocs",
            p4_source="p4src/ocs.p4",
        )

        # Launch run.sh (builds C++ and starts bf_switchd)
        self._launch_via_runsh(
            ssh, role="ocs",
            remote_workdir=remote_workdir,
            subdir="emulated-ocs",
        )

        # Wait for BFRt, run setup script via bfshell over SSH, fetch log
        self._wait_for_bfrt(ssh, host, self._bfrt_port, self._bfrt_timeout)
        self._run_setup_via_bfshell(
            ssh, role="ocs",
            remote_workdir=remote_workdir,
            subdir="emulated-ocs",
            setup_script="setup_ocs.py",
        )
        self._fetch_remote_log(ssh, "ocs")
        addr = f"{host}:{self._bfrt_port}"
        logger.info("OCS ready at %s", addr)
        return addr

    def deploy_tors(
        self,
        remote_workdir: str = "/tmp/openoptics",
    ) -> Dict[str, str]:
        """Deploy and start all ToR switches in parallel.

        SSH connections are established sequentially (may need interactive
        password prompts), then the slow work (upload, P4 build, launch,
        setup) runs concurrently across all physical switches.

        Returns ``{"tor0": "host:port", ...}``.
        """
        tor_switches = self._config.get("physical_switch", self._config.get("tor_switches", []))
        if not tor_switches:
            return {}

        # Phase 1: open all SSH connections on the main thread so that
        # any interactive password prompt is visible to the user.
        self._ensure_jump_host()
        ssh_conns = []
        for tor_sw_cfg in tor_switches:
            host = tor_sw_cfg["host"]
            logical_tors = tor_sw_cfg.get("logical_tor", [])
            tor_ids = [t["tor_id"] for t in logical_tors] if logical_tors else tor_sw_cfg.get("tor_ids", [])
            sw_key = f"tor{tor_ids[0]}" if tor_ids else host
            logger.info("Connecting to ToR %s (tor_ids=%s) ...", host, tor_ids)
            ssh = self.ssh_connect(tor_sw_cfg)
            self._ssh_clients[sw_key] = ssh
            ssh_conns.append((sw_key, host, ssh, tor_sw_cfg))

        # Phase 2: deploy all switches in parallel.
        grpc_addrs: Dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=len(ssh_conns)) as executor:
            future_to_key = {
                executor.submit(
                    self._deploy_single_tor,
                    sw_key, host, ssh, remote_workdir,
                ): sw_key
                for sw_key, host, ssh, _ in ssh_conns
            }
            for future in as_completed(future_to_key):
                sw_key, addr = future.result()
                grpc_addrs[sw_key] = addr

        return grpc_addrs

    def _deploy_single_tor(
        self,
        sw_key: str,
        host: str,
        ssh,
        remote_workdir: str,
    ) -> tuple:
        """Deploy a single physical ToR switch (SSH already connected).

        Returns ``(sw_key, grpc_addr)`` on success.
        """
        logger.info("Deploying ToR %s (%s) ...", sw_key, host)

        # Upload openoptics-tor/ directory
        local_dir = self._tofino_repo / "openoptics-tor"
        remote_dir = remote_workdir + "/openoptics-tor"
        self._upload_dir(ssh, local_dir, remote_dir)

        # Compile P4 on the switch (blocking)
        self._build_p4(
            ssh, remote_workdir=remote_workdir,
            subdir="openoptics-tor",
            p4_source="p4src/openoptics_tor.p4",
        )

        # Launch run.sh (builds C++ and starts bf_switchd)
        self._launch_via_runsh(
            ssh, role="tor",
            remote_workdir=remote_workdir,
            subdir="openoptics-tor",
        )

        # Wait for BFRt, run setup script via bfshell over SSH, fetch log
        self._wait_for_bfrt(ssh, host, self._bfrt_port, self._bfrt_timeout)
        self._run_setup_via_bfshell(
            ssh, role="tor",
            remote_workdir=remote_workdir,
            subdir="openoptics-tor",
            setup_script="setup_tor.py",
        )
        self._fetch_remote_log(ssh, "tor", tag=sw_key)
        addr = f"{host}:{self._bfrt_port}"
        logger.info("ToR switch ready at %s", addr)
        return sw_key, addr

    def connect_server(self, host_ip: str, user: str = None, key_file: str = None,
                       connect_timeout: int = None) -> object:
        """Open an SSH connection to an end-host server, optionally via jump host.

        Connections are cached in ``_ssh_clients`` under the key
        ``"server_<ip>"``.  Subsequent calls with the same IP return the
        existing connection.

        Args:
            host_ip: Server IP address (from logical_tor.host_ip).
            user: SSH username (defaults to ``[servers].user`` in config).
            key_file: SSH key (defaults to ``[servers].key_file``).
            connect_timeout: Timeout (defaults to ``[servers].connect_timeout``).

        Returns:
            A connected paramiko SSHClient.
        """
        cache_key = f"server_{host_ip}"
        if cache_key in self._ssh_clients:
            return self._ssh_clients[cache_key]

        srv_defaults = self._config.get("servers", {})
        cfg = {
            "host": host_ip,
            "user": user or srv_defaults.get("user", "root"),
            "key_file": key_file or srv_defaults.get("key_file", "~/.ssh/id_rsa"),
            "connect_timeout": connect_timeout or srv_defaults.get("connect_timeout", 10),
        }
        ssh = self.ssh_connect(cfg)
        self._ssh_clients[cache_key] = ssh
        return ssh

    def get_ssh_clients(self) -> Dict[str, object]:
        """Return a copy of the active SSH client dict."""
        return dict(self._ssh_clients)

    def stop_all(self) -> None:
        """Kill control-plane processes on all switches via SSH."""
        kill_cmd = "sudo pkill -9 -x openoptics_tor; sudo pkill -9 -x ocs; sudo pkill -9 -x bf_switchd; sleep 2"
        for sw_key, ssh in self._ssh_clients.items():
            try:
                logger.info("Stopping control plane on %s ...", sw_key)
                stdin, stdout, stderr = ssh.exec_command(kill_cmd)
                stdout.channel.recv_exit_status()
            except Exception as exc:
                logger.warning("stop_all: error on %s: %s", sw_key, exc)
        self._close_all()

    # ------------------------------------------------------------------
    # SSH connection helpers (kept from previous implementation)
    # ------------------------------------------------------------------

    def _ensure_jump_host(self) -> None:
        """Eagerly connect to the jump host (if configured).

        Call this before spawning threads so that any interactive
        password prompt happens on the main thread.
        """
        if "jump_host" not in self._config:
            return
        if self._jump_client is not None:
            return
        self._init_jump_client()

    def _init_jump_client(self) -> None:
        """Establish the SSH connection to the jump host."""
        jcfg = self._config["jump_host"]
        jhost = jcfg["host"]
        juser = jcfg.get("user", "p4")
        jkey = os.path.expanduser(jcfg.get("key_file", "~/.ssh/id_rsa"))
        jtimeout = jcfg.get("connect_timeout", 30)

        jkey_resolved = jkey if os.path.exists(jkey) else None
        logger.debug("SSH connecting to jump host %s@%s ... Key file: %s (resolved: %s)",
                    juser, jhost, jkey, jkey_resolved)
        try:
            jclient = self._paramiko_connect(
                hostname=jhost,
                username=juser,
                key_filename=jkey_resolved,
                timeout=jtimeout,
                label=" (jump host)",
            )
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"SSH connection to jump host {juser}@{jhost} failed: {exc}\n"
                f"  Check host/user/key_file/connect_timeout under [jump_host] "
                f"in config.toml."
            ) from exc
        self._jump_client = jclient
        logger.debug("Connected to jump host %s.", jhost)

        # Fetch the jump host's private key for target switch auth
        self._jump_pkey = self._fetch_jump_key(jclient, jcfg)

    def _get_jump_socket(self, host: str, port: int = 22):
        """Return a paramiko forwarding channel tunnelled through the jump host."""
        if self._jump_client is None:
            self._init_jump_client()

        transport = self._jump_client.get_transport()
        timeout = self._config["jump_host"].get("connect_timeout", 30)
        try:
            return transport.open_channel(
                "direct-tcpip", (host, port), ("", 0), timeout=timeout,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to open tunnel to {host}:{port} through jump host: {exc}\n"
                f"  Verify from the jump host: ssh {host} or nc -zv {host} {port}"
            ) from exc

    @staticmethod
    def _fetch_jump_key(ssh_client, jcfg: dict):
        """Read the jump host's private key via SFTP and return a paramiko PKey."""
        import io
        import paramiko

        remote_key = jcfg.get("target_key_file", "~/.ssh/id_rsa")
        if remote_key.startswith("~"):
            remote_key = remote_key.replace("~", f"/home/{jcfg.get('user', 'p4')}", 1)

        logger.debug("Fetching private key from jump host: %s", remote_key)
        try:
            sftp = ssh_client.open_sftp()
            try:
                with sftp.file(remote_key, "r") as f:
                    key_data = f.read()
            finally:
                sftp.close()
        except Exception as exc:
            logger.warning("Could not fetch key '%s' from jump host: %s", remote_key, exc)
            return None

        key_file = io.StringIO(key_data.decode())
        for key_class in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey):
            try:
                key_file.seek(0)
                return key_class.from_private_key(key_file)
            except Exception:
                continue
        logger.warning("Could not parse private key from jump host (unsupported type).")
        return None

    def ssh_connect(self, sw_cfg: dict):
        """Open an SSH connection to a switch, optionally through a jump host."""
        host = sw_cfg["host"]
        user = sw_cfg.get("user", "p4")
        key_file = os.path.expanduser(sw_cfg.get("key_file", "~/.ssh/id_rsa"))
        connect_timeout = sw_cfg.get("connect_timeout", 30)

        use_jump = (
            "jump_host" in self._config
            and sw_cfg.get("jump_host", True) is not False
        )
        jump_info = (
            f" via {self._config['jump_host']['host']}" if use_jump else ""
        )
        logger.debug("SSH connecting to %s@%s%s (timeout=%ds) ...",
                    user, host, jump_info, connect_timeout)

        key_file_resolved = key_file if os.path.exists(key_file) else None
        logger.debug("Key file: %s (resolved: %s)", key_file, key_file_resolved)
        sock_factory = (lambda: self._get_jump_socket(host)) if use_jump else None
        sock = sock_factory() if sock_factory else None
        pkey = self._jump_pkey if use_jump else None

        try:
            client = self._paramiko_connect(
                hostname=host,
                username=user,
                key_filename=key_file_resolved,
                timeout=connect_timeout,
                sock=sock,
                sock_factory=sock_factory,
                pkey=pkey,
                label=jump_info,
            )
        except RuntimeError:
            raise
        except Exception as exc:
            if use_jump:
                jhost = self._config["jump_host"]["host"]
                msg = (
                    f"SSH connection to {user}@{host} via jump host {jhost} failed: {exc}\n"
                    f"  Checklist:\n"
                    f"    1. Is the jump host reachable?          ping {jhost}\n"
                    f"    2. Can you SSH through the jump host?   ssh -J {jhost} {user}@{host}\n"
                    f"    3. Is the key file correct?             key_file = {key_file}\n"
                    f"    4. Adjust connect_timeout in config.toml (current: {connect_timeout}s)"
                )
            else:
                msg = (
                    f"SSH connection to {user}@{host} failed: {exc}\n"
                    f"  Checklist:\n"
                    f"    1. Is the switch reachable?   ping {host}\n"
                    f"    2. Is SSH running?            ssh {user}@{host}\n"
                    f"    3. Is the key file correct?   key_file = {key_file}\n"
                    f"    4. Adjust connect_timeout in config.toml (current: {connect_timeout}s)"
                )
            raise RuntimeError(msg) from exc
        logger.debug("SSH connected to %s@%s%s.", user, host, jump_info)
        return client

    @staticmethod
    def _is_auth_error(exc: Exception) -> bool:
        """Return True if *exc* indicates an SSH authentication failure."""
        try:
            import paramiko
            if isinstance(exc, paramiko.AuthenticationException):
                return True
        except ImportError:
            pass
        msg = str(exc).lower()
        return "authentication" in msg or "no authentication methods" in msg

    @staticmethod
    def _paramiko_connect(
        hostname: str,
        username: str,
        key_filename: Optional[str],
        timeout: int,
        sock=None,
        sock_factory=None,
        pkey=None,
        label: str = "",
    ):
        """Create an SSH client and connect with key-based auth, falling back to password."""
        try:
            import paramiko
        except ImportError as exc:
            raise ImportError(
                "The 'paramiko' package is required for Tofino SSH deployment. "
                "Install it with: pip install paramiko"
            ) from exc

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=hostname,
                username=username,
                pkey=pkey,
                key_filename=key_filename,
                look_for_keys=(pkey is None and key_filename is None),
                allow_agent=(pkey is None),
                timeout=timeout,
                sock=sock,
            )
        except Exception as exc:
            if TofinoDeployer._is_auth_error(exc):
                logger.warning(
                    "Key-based auth to %s@%s%s failed: %s. "
                    "Falling back to password.",
                    username, hostname, label, exc,
                )
                import getpass
                password = getpass.getpass(f"Password for {username}@{hostname}{label}: ")
                retry_sock = sock_factory() if sock_factory else sock
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                try:
                    client.connect(
                        hostname=hostname,
                        username=username,
                        password=password,
                        look_for_keys=False,
                        allow_agent=False,
                        timeout=timeout,
                        sock=retry_sock,
                    )
                except Exception as exc2:
                    raise RuntimeError(
                        f"SSH authentication to {username}@{hostname}{label} failed: {exc2}"
                    ) from exc2
            else:
                raise
        return client

    # ------------------------------------------------------------------
    # Deployment helpers
    # ------------------------------------------------------------------

    # Files to skip during upload (compiled binaries, large precomputed tables)
    _UPLOAD_SKIP = {"openoptics_tor", "ocs", ".git"}

    def _upload_dir(self, ssh, local_dir: Path, remote_dir: str) -> None:
        """Recursively upload a local directory to the remote host via SFTP."""
        # Wait for mkdir to complete before starting SFTP
        stdin, stdout, stderr = ssh.exec_command(f"mkdir -p {remote_dir}")
        stdout.channel.recv_exit_status()
        sftp = ssh.open_sftp()
        try:
            self._sftp_put_dir(sftp, local_dir, remote_dir)
        finally:
            sftp.close()

    def _sftp_put_dir(self, sftp, local_dir: Path, remote_dir: str) -> None:
        """Recursively upload *local_dir* → *remote_dir* via SFTP."""
        try:
            sftp.mkdir(remote_dir)
        except OSError:
            pass  # directory may already exist

        for item in sorted(local_dir.iterdir()):
            if item.name in self._UPLOAD_SKIP:
                continue
            remote_path = remote_dir + "/" + item.name
            if item.is_dir():
                self._sftp_put_dir(sftp, item, remote_path)
            else:
                logger.debug("SCP  %s → %s", item, remote_path)
                sftp.put(str(item), remote_path)

    def _build_p4(
        self,
        ssh,
        remote_workdir: str,
        subdir: str,
        p4_source: str,
        timeout: int = 600,
    ) -> None:
        """Compile a P4 program on the remote switch.

        Runs ``$SDE/p4_build.sh <p4_source> --with-tofino2`` as a blocking
        SSH command.  The compiled artifacts (.conf, .bfrt.json, pipe binaries)
        are installed to ``$SDE_INSTALL/share/p4/targets/tofino2/``.

        Args:
            ssh: Active SSH client to the switch.
            remote_workdir: Remote base directory (e.g. ``/tmp/openoptics``).
            subdir: Subdirectory containing P4 sources (``openoptics-tor`` or
                ``emulated-ocs``).
            p4_source: Path to the top-level P4 file relative to subdir
                (e.g. ``p4src/openoptics_tor.p4``).
            timeout: Maximum seconds to wait for compilation.
        """
        if not self._build_p4_flag:
            logger.info("P4 build skipped (build_p4 = false in config).")
            return

        nb_slices = getattr(self, '_nb_time_slices', None)
        if nb_slices is None:
            raise RuntimeError(
                "nb_time_slices not set on deployer. "
                "This is set by TofinoBackend.setup() — ensure setup() runs before P4 build."
            )
        nb_link = getattr(self, '_nb_link', None)
        if nb_link is None:
            raise RuntimeError(
                "nb_link not set on deployer. "
                "This is set by TofinoBackend.setup() — ensure setup() runs before P4 build."
            )

        logger.info("Compiling P4 program %s/%s with SLICE_NUM=%d PORT_NUM=%d ...",
                     subdir, p4_source, nb_slices, nb_link)
        cmd = (
            f"source {self._sde_path}/set_sde.bash && "
            f"export SDE_INSTALL={self._sde_install} && "
            f"cd {remote_workdir}/{subdir} && "
            f"$SDE/p4_build.sh {p4_source} --with-tofino2 "
            f"-D SLICE_NUM={nb_slices} -D PORT_NUM={nb_link}"
        )
        _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        if exit_code != 0:
            stdout_tail = stdout.read().decode()[-2000:]
            stderr_tail = stderr.read().decode()[-2000:]
            raise RuntimeError(
                f"P4 build failed for {p4_source} (exit {exit_code}).\n"
                f"--- stdout (last 2000 chars) ---\n{stdout_tail}\n"
                f"--- stderr (last 2000 chars) ---\n{stderr_tail}"
            )
        logger.info("P4 build succeeded for %s/%s.", subdir, p4_source)

    def _launch_via_runsh(
        self,
        ssh,
        role: str,
        remote_workdir: str,
        subdir: str,
    ) -> None:
        """Launch run.sh in the background on the remote switch.

        Sources ``set_sde.bash``, sets ``OPENOPTICS_DAEMON=1`` so the binary
        stays alive in headless mode, then runs ``run.sh`` with nohup.
        run.sh reads all parameters from openoptics_config.json.
        """
        # Kill any previous instance and wait for ports to be released.
        kill_cmd = (
            "sudo pkill -9 -x openoptics_tor ; "
            "sudo pkill -9 -x ocs ; "
            "sudo pkill -9 -x bfshell ; "
            "sudo pkill -9 -x bf_switchd ; "
            "sleep 2 ; "
            # Wait up to 10s for Thrift port 9090 to be free
            "for i in $(seq 1 10); do "
            "  ss -tlnp 2>/dev/null | grep -q ':9090 ' || break ; "
            "  sleep 1 ; "
            "done"
        )
        logger.debug("Killing previous instances on remote ...")
        _, stdout, _ = ssh.exec_command(kill_cmd, timeout=20)
        stdout.channel.recv_exit_status()

        log_file = f"/tmp/openoptics_{role}.log"
        cmd = (
            f"nohup bash -c '"
            f"source {self._sde_path}/set_sde.bash && "
            f"export SDE_INSTALL={self._sde_install} && "
            f"export OPENOPTICS_DAEMON=1 && "
            f"cd {remote_workdir}/{subdir} && "
            f"chmod +x run.sh && "
            f"stdbuf -oL ./run.sh"
            f"' > {log_file} 2>&1 &"
        )
        logger.debug("Launching %s via run.sh ...", role)
        ssh.exec_command(cmd)

    def _run_setup_via_bfshell(
        self,
        ssh,
        role: str,
        remote_workdir: str,
        subdir: str,
        setup_script: str,
        timeout: int = 120,
    ) -> None:
        """Run a setup script on the remote switch via bfshell over SSH.

        All configuration (SLICE_DURATION, ARCH, PORT_NUM, etc.) is read
        from ``openoptics_config.json`` by the setup script itself — no
        env vars or wrapper needed.

        bfshell cannot be launched from within the C++ bf_switchd process
        (it cannot connect back to its parent).  Running it as a separate
        SSH command works reliably.
        """
        script_path = f"{remote_workdir}/{subdir}/{setup_script}"
        cmd = (
            f"source {self._sde_path}/set_sde.bash && "
            f"export SDE_INSTALL={self._sde_install} && "
            f"export SETUP_SCRIPT={script_path} && "
            f"cd {remote_workdir}/{subdir} && "
            f"$SDE_INSTALL/bin/bfshell -b {script_path} 2>&1"
        )
        logger.info("Running %s setup via bfshell on remote ...", role)
        try:
            _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
            output = stdout.read().decode()
            exit_code = stdout.channel.recv_exit_status()

            # Append bfshell output to the remote log file for diagnostics
            append_cmd = f"cat >> /tmp/openoptics_{role}.log << 'BFSHELL_EOF'\n{output}\nBFSHELL_EOF"
            ssh.exec_command(append_cmd)

            if "[OpenOptics] Loaded" in output or "[OpenOptics] Setup complete" in output or "[OpenOptics] OCS setup complete" in output:
                for line in output.splitlines():
                    if "[OpenOptics]" in line:
                        logger.info("%s: %s", role.upper(), line.strip())
            else:
                last_lines = "\n".join(output.strip().splitlines()[-10:])
                raise RuntimeError(
                    f"{role.upper()} setup script failed (exit {exit_code}).\n"
                    f"The [OpenOptics] marker was not found in bfshell output.\n"
                    f"This usually means a stale bfshell/bf_switchd process is "
                    f"holding the Python shell lock. Kill it on the switch and retry.\n"
                    f"Last output:\n{last_lines}"
                )
        except Exception as exc:
            logger.error("%s setup via bfshell failed: %s", role.upper(), exc)

    def _fetch_remote_log(self, ssh, role: str, local_dir: str = "/tmp", tag: str = "") -> None:
        """Download the remote switch log to a local file via SFTP."""
        remote_path = f"/tmp/openoptics_{role}.log"
        suffix = f"_{tag}" if tag else ""
        local_path = os.path.join(local_dir, f"openoptics_{role}{suffix}_remote.log")
        try:
            sftp = ssh.open_sftp()
            try:
                sftp.get(remote_path, local_path)
            finally:
                sftp.close()
            logger.debug("Fetched %s switch log → %s", role, local_path)
        except Exception as exc:
            logger.warning("Could not fetch %s log: %s", role, exc)

    def _wait_for_bfrt(self, ssh, host: str, port: int, timeout: int) -> None:
        """Poll until the BFRt gRPC port accepts connections via SSH."""
        logger.debug("Waiting for BFRt gRPC at %s:%d (timeout=%ds) ...", host, port, timeout)
        check_cmd = f"bash -c 'echo > /dev/tcp/localhost/{port}' 2>/dev/null"
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                stdin, stdout, stderr = ssh.exec_command(check_cmd, timeout=5)
                exit_code = stdout.channel.recv_exit_status()
                if exit_code == 0:
                    logger.info("BFRt gRPC at %s:%d is ready.", host, port)
                    return
            except Exception:
                pass
            time.sleep(2)
        raise TimeoutError(
            f"BFRt gRPC not available at {host}:{port} after {timeout}s. "
            "Check the control-plane log at /tmp/openoptics_*.log on the switch."
        )

    def _close_all(self) -> None:
        for client in self._ssh_clients.values():
            try:
                client.close()
            except Exception:
                pass
        self._ssh_clients.clear()
        if self._jump_client is not None:
            try:
                self._jump_client.close()
            except Exception:
                pass
            self._jump_client = None
