#!/usr/bin/env python3
"""Generate a Tofino backend config template in the user's working directory.

After ``pip install openoptics-dcn[tofino]``, run::

    openoptics-gen-config                  # writes ./openoptics-tofino.toml
    openoptics-gen-config -o mytestbed.toml
    openoptics-gen-config --force          # overwrite an existing file

The written file is a complete Tofino backend config with placeholder values
(``USER``, ``jumphost.example.com``, IP/MAC placeholders, etc.).  Edit it in
place with your testbed values, then pass it to ``TofinoBackend``::

    TofinoBackend().setup(..., config_file="openoptics-tofino.toml")
"""
from __future__ import annotations

import argparse
import sys
try:
    from importlib.resources import files  # Python >= 3.9
except ImportError:  # pragma: no cover
    from importlib_resources import files  # type: ignore[import-not-found]
from pathlib import Path


TEMPLATE_NAME = "config_4tor.toml"
DEFAULT_OUTPUT = "openoptics-tofino.toml"


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="openoptics-gen-config",
        description="Generate an editable Tofino backend config template.",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=Path.cwd() / DEFAULT_OUTPUT,
        help=f"Destination path (default: ./{DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the output file if it already exists.",
    )
    args = parser.parse_args()

    template = files("openoptics.backends.tofino") / TEMPLATE_NAME
    if not template.is_file():
        print(f"error: template {TEMPLATE_NAME} not found in installed package",
              file=sys.stderr)
        return 1

    if args.output.exists() and not args.force:
        print(
            f"error: {args.output} already exists. "
            f"Pass --force to overwrite, or -o PATH to choose a different path.",
            file=sys.stderr,
        )
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(template.read_text())
    print(f"wrote {args.output}")
    print(f"       edit the placeholder values (USER, jumphost.example.com, "
          f"IP/MAC fields), then pass config_file={args.output.name!r} to TofinoBackend.setup().")
    return 0


if __name__ == "__main__":
    sys.exit(main())
