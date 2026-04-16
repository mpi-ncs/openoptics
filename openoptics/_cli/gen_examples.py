"""Copy the bundled examples/ folder into the user's working directory.

Run after ``pip install openoptics-dcn``::

    openoptics-gen-examples                  # writes ./examples/
    openoptics-gen-examples -o my_examples   # custom destination
    openoptics-gen-examples --force          # overwrite an existing directory
"""
from __future__ import annotations

import sys

from openoptics._cli._copy_bundle import copy_bundle


def main() -> int:
    return copy_bundle(
        prog="openoptics-gen-examples",
        package="openoptics._bundled_examples",
        default_dest_name="examples",
        description="Copy the bundled OpenOptics examples into the current directory.",
    )


if __name__ == "__main__":
    sys.exit(main())
