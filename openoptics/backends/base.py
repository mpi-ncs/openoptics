# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# Author: Yiming Lei (ylei@mpi-inf.mpg.de)
#
# This software is licensed for non-commercial scientific research purposes only.
#
# License text: Creative Commons NC BY SA 4.0
# https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


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
    """

    supports_device_manager: bool = True

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
        guardband_ms: int,
        tor_host_port: int,
        host_tor_port: int,
        tor_ocs_ports: list,
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
