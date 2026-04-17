"""Copy the bundled tutorials/ folder into the user's working directory.

Run after ``pip install openoptics-dcn``::

    openoptics-gen-tutorials                   # writes ./tutorials/
    openoptics-gen-tutorials -o my_tutorials   # custom destination
    openoptics-gen-tutorials --force           # overwrite an existing directory
"""
from __future__ import annotations

import sys

from openoptics._cli._copy_bundle import copy_bundle


def main() -> int:
    return copy_bundle(
        prog="openoptics-gen-tutorials",
        package="openoptics._bundled_tutorials",
        default_dest_name="tutorials",
        description="Copy the bundled OpenOptics tutorials into the current directory.",
    )


if __name__ == "__main__":
    sys.exit(main())
