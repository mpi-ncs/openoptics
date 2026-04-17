# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# Author: Yiming Lei (ylei@mpi-inf.mpg.de)
#
# This software is licensed for non-commercial scientific research purposes only.
#
# License text: Creative Commons NC BY SA 4.0
# https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en

from openoptics.backends.base import BackendBase, SwitchHandle


_EXTRA_HINTS = {
    "Mininet": "pip install 'openoptics-dcn[mininet]' (also requires BMv2 installed at /behavioral-model, typically provided by the Docker image ymlei/openoptics)",
    "Tofino":  "pip install 'openoptics-dcn[tofino]' (also requires SSH access to a switch with the Tofino SDE installed)",
    "ns3":     "pip install 'openoptics-dcn[ns3]' (also requires an ns-3 installation; set NS3_DIR)",
}


def create_backend(backend_name: str) -> BackendBase:
    """Instantiate and return the backend for the given name.

    Args:
        backend_name: "Mininet", "ns3", or "Tofino"

    Returns:
        A BackendBase instance.
    """
    try:
        if backend_name == "Mininet":
            from openoptics.backends.mininet.backend import MininetBackend
            return MininetBackend()
        elif backend_name == "Tofino":
            from openoptics.backends.tofino.backend import TofinoBackend
            return TofinoBackend()
        elif backend_name == "ns3":
            from openoptics.backends.ns3.backend import Ns3Backend
            return Ns3Backend()
        else:
            raise ValueError(f"Unsupported backend: {backend_name}")
    except ImportError as e:
        hint = _EXTRA_HINTS.get(backend_name, "")
        raise ImportError(
            f"Failed to load the {backend_name} backend: {e}. "
            + (f"Install the optional dependencies with: {hint}" if hint else "")
        ) from e
