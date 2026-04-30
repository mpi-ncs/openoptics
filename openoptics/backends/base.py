# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# Author: Yiming Lei (ylei@mpi-inf.mpg.de)
#
# This software is licensed for non-commercial scientific research purposes only.
#
# License text: Creative Commons NC BY SA 4.0
# https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en

import warnings
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


def warn_if_overhead_exhausts_slice(
    *,
    guardband_us: int,
    slice_duration_us: int,
    link_delay_us: int = 0,
    backend_name: str,
) -> None:
    """Warn if per-slice timing overhead leaves no room for payload.

    Each backend computes its own effective overhead and calls this once
    from ``setup()``. Backends without a parameterized link delay (Tofino,
    or Mininet after it folds ``link_delay_ms`` into ``guardband_us``)
    pass ``link_delay_us=0``.
    """
    overhead_us = guardband_us + link_delay_us
    if overhead_us >= slice_duration_us:
        delay_term = f" + link_delay_us ({link_delay_us})" if link_delay_us else ""
        warnings.warn(
            f"[{backend_name}] guardband_us ({guardband_us}){delay_term} "
            f">= time_slice_duration_us ({slice_duration_us}); "
            f"no packets will cross the OCS for this run.",
            RuntimeWarning,
            stacklevel=3,
        )


@dataclass
class TableEntry:
    """A single P4 table entry, expressed in backend-agnostic terms.

    Each backend translates these to its native format:
    - Mininet/BMv2: reconstructs runtime_CLI strings
    - Tofino: calls BFRt Python API

    Attributes:
        table: Logical table name, e.g. ``"ocs_schedule"``, ``"per_hop_routing"``.
        action: Logical action name, e.g. ``"ocs_forward"``, ``"write_time_flow_entry"``.
        match_keys: Ordered dict of match field name → value. Insertion order is
            preserved (Python 3.7+) and is significant for positional CLI formats.
        action_params: Ordered dict of action parameter name → value. For source-
            routing entries the special key ``"hops"`` maps to a list of
            ``(cur_node, send_ts, send_port)`` tuples (one per hop).
        is_default_action: When ``True``, this entry sets the table's default action
            (``table_set_default`` in BMv2 CLI) rather than adding a match rule.
    """
    table: str
    action: str
    match_keys: dict = field(default_factory=dict)
    action_params: dict = field(default_factory=dict)
    is_default_action: bool = False


class SwitchHandle:
    """A backend-agnostic reference to a switch."""

    def __init__(self, name: str, thrift_port: int):
        self.name = name
        self.thrift_port = thrift_port


class BackendBase(ABC):
    """Abstract base class for OpenOptics backends.

    Implement this class to add support for a new backend (e.g. ns-3, Tofino).
    ``BaseNetwork`` and ``DeviceManager`` interact with the network exclusively
    through this interface, keeping them backend-agnostic.

    Subclass attributes
    -------------------
    supports_device_manager : bool
        If False, ``start_monitor()`` skips DeviceManager creation (which
        requires BMv2 Thrift).  Tofino uses BFRt gRPC instead.
    supports_dashboard_without_device_manager : bool
        If True, ``start_monitor()`` may still start the dashboard even when
        there is no DeviceManager.  Simulator backends use this to publish
        their own event-driven telemetry.
    supports_cli : bool
        If False, ``BaseNetwork.start()`` skips the interactive OpticalCLI
        and calls ``self.run()`` on the backend instead.  Used by simulation
        backends (ns-3) where there is no live network to interact with; the
        whole scenario is scripted up front and ``run()`` just advances the
        simulator.
    """

    supports_device_manager: bool = True
    supports_dashboard_without_device_manager: bool = False
    supports_cli: bool = True

    # Maximum number of transmit hops the source-routing data plane can
    # carry per packet. Set by each backend to its action/header limit
    # (Mininet P4 SR header tops out at 3, Tofino's SR action at 2, ns-3
    # ``OpenOpticsSourceRouteHeader::kMaxHops`` at 16). ``None`` = no
    # declared cap; ``BaseNetwork.deploy_routing`` consults this when
    # ``routing_mode="Source"`` and warns if any path exceeds it.
    max_source_route_hops: Optional[int] = None

    def run(self) -> None:
        """Run the backend (simulator) to completion.

        Only called by :meth:`BaseNetwork.start` when ``supports_cli`` is
        False.  Default implementation is a no-op so non-simulator backends
        don't need to override it.
        """

    def setup_dashboard(self, service) -> None:
        """Wire backend-specific collectors / event sources into the dashboard.

        Called by :meth:`BaseNetwork.start_monitor` after ``DashboardService``
        has been created + epoched, and after any default
        ``DeviceMetricCollector`` has been registered. Simulator backends
        (ns-3) override this to register a Python sink and connect their
        ns-3 ``TraceSource`` hooks. Default: no-op.

        Args:
            service: The live ``DashboardService``; use its
                ``register_event_source`` / ``register_collector`` methods.
        """

    @classmethod
    def accepted_kwargs(cls) -> set:
        """Return the names of backend-specific keyword arguments accepted by ``setup()``.

        Override in subclasses to declare backend-specific parameters.
        ``BaseNetwork.__init__`` validates user-supplied ``**backend_kwargs``
        against this set and raises ``ValueError`` for unknown names.
        """
        return set()

    @abstractmethod
    def setup(
        self,
        *,
        nb_node: int,
        nb_host_per_tor: int,
        nb_link: int,
        nb_time_slices: int,
        time_slice_duration_us: int,
        guardband_us: int,
        calendar_queue_mode: int,
        **backend_kwargs,
    ) -> None:
        """Create backend nodes and start the network.

        After this call, ``get_switch()``, ``get_tor_switches()``, and
        ``get_ip_to_tor()`` must return valid data.

        Args:
            **backend_kwargs: Backend-specific parameters declared via
                ``accepted_kwargs()``.  Unknown keys are rejected earlier by
                ``BaseNetwork.__init__``, so subclasses may safely consume
                whatever they declared.
        """

    @abstractmethod
    def get_switch(self, name: str) -> SwitchHandle:
        """Return a SwitchHandle for the named switch."""

    @abstractmethod
    def switch_exists(self, name: str) -> bool:
        """Return True if a switch with the given name exists."""

    @abstractmethod
    def get_tor_switches(self) -> list:
        """Return a list of SwitchHandle for all ToR switches."""

    def get_optical_switches(self) -> list:
        """Return a list of SwitchHandle for all optical (OCS) switches.

        Default returns ``[]`` so backends without OCS device-plane telemetry
        need no override.
        """
        return []

    @abstractmethod
    def get_ip_to_tor(self) -> dict:
        """Return the {ip_str: tor_id} mapping populated during setup."""

    @abstractmethod
    def load_table(
        self,
        switch_name: str,
        entries: list,
        print_flag: bool = False,
        save_flag: bool = False,
        save_name: str = "saved_commands",
    ) -> bool:
        """Load P4 table entries to the named switch.

        Args:
            switch_name: Name of the switch (e.g. "ocs", "tor0").
            entries: List of :class:`TableEntry` objects to install.
            print_flag: Print backend output if True.
            save_flag: Save a human-readable representation to a file if True.
            save_name: Filename stem used when save_flag is True.

        Returns:
            True on success.
        """

    @abstractmethod
    def clear_table(
        self,
        switch_name: str,
        table: str,
        print_flag: bool = False,
    ) -> None:
        """Clear all entries from a P4 table on the named switch.

        Args:
            switch_name: Name of the switch (e.g. "ocs", "tor0").
            table: Logical table name (e.g. ``"ocs_schedule"``).  Each backend
                maps this to its internal table identifier.
            print_flag: Print backend output if True.
        """

    @abstractmethod
    def stop(self) -> None:
        """Stop the network."""

    @abstractmethod
    def cleanup(self) -> None:
        """Clean up residual state (e.g. stale processes, network namespaces)."""

    def get_cli_commands(self) -> dict:
        """Return backend-specific CLI commands to register on OpticalCLI.

        Returns:
            A dict of ``{command_name: (fn, docstring)}`` where
            ``fn(cli, line)`` is called when the user types the command.
        """
        return {}

    def default_handler(self, line: str) -> bool:
        """Handle an unrecognised CLI line.

        Return True if the backend handled the command, False to fall through
        to OpticalCLI's default error message.
        """
        return False
