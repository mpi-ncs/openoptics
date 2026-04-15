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


def create_backend(backend_name: str) -> BackendBase:
    """Instantiate and return the backend for the given name.

    Args:
        backend_name: "Mininet", "ns3", or "Tofino"

    Returns:
        A BackendBase instance.
    """
    if backend_name == "Mininet":
        from openoptics.backends.mininet.backend import MininetBackend
        return MininetBackend()
    elif backend_name == "Tofino":
        from openoptics.backends.tofino.backend import TofinoBackend
        return TofinoBackend()
    else:
        raise ValueError(f"Unsupported backend: {backend_name}")
