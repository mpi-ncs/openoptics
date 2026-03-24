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
        time_slice_duration_ms: int,
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

    @abstractmethod
    def get_ip_to_tor(self) -> dict:
        """Return the {ip_str: tor_id} mapping populated during setup."""

    @abstractmethod
    def load_table(
        self,
        switch_name: str,
        table_commands: str,
        print_flag: bool = False,
        save_flag: bool = False,
        save_name: str = "saved_commands",
    ) -> bool:
        """Load P4 table entries to the named switch.

        Args:
            switch_name: Name of the switch (e.g. "ocs", "tor0").
            table_commands: Multi-line string of runtime CLI commands.
            print_flag: Print the CLI output if True.
            save_flag: Save commands to a file if True.
            save_name: Filename stem used when save_flag is True.

        Returns:
            True on success.
        """

    @abstractmethod
    def clear_table(
        self,
        switch_name: str,
        table_name: str,
        print_flag: bool = False,
    ) -> None:
        """Clear all entries from a P4 table on the named switch.

        Args:
            switch_name: Name of the switch (e.g. "ocs", "tor0").
            table_name: Fully-qualified P4 table name.
            print_flag: Print the CLI output if True.
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
