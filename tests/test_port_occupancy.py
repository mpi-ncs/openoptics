# This file is superseded by test_toolbox.py which provides proper unit tests
# for BaseNetwork.connect() and BaseNetwork.disconnect().
# Kept to avoid breaking any external references.

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from test_toolbox import *  # noqa: F401, F403

if __name__ == "__main__":
    unittest.main()
