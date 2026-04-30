# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# License: Creative Commons NC BY SA 4.0
#
# Conditional-skip helper for ns-3-backed tests. Not a test file.

import importlib
import os
import unittest


def ns3_available() -> bool:
    """Return True iff NS3_DIR is set and the `ns` module imports cleanly."""
    if not os.environ.get("NS3_DIR"):
        return False
    try:
        importlib.import_module("ns")
    except Exception:
        return False
    return True


skip_if_no_ns3 = unittest.skipUnless(
    ns3_available(),
    "ns-3 Python bindings unavailable; set NS3_DIR + PYTHONPATH "
    "(see openoptics-install-ns3)",
)
