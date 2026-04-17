"""Shared helper: copy a bundled resource tree from the installed package into
the user's working directory.

Used by ``openoptics-gen-examples`` and ``openoptics-gen-tutorials``.
"""
from __future__ import annotations

import argparse
import shutil
import sys
try:
    from importlib.resources import as_file, files  # Python >= 3.9
except ImportError:  # pragma: no cover
    from importlib_resources import as_file, files  # type: ignore[import-not-found]
from pathlib import Path


def copy_bundle(
    *,
    prog: str,
    package: str,
    default_dest_name: str,
    description: str,
) -> int:
    """Parse `-o/--output` and `--force`, then copy `package` out to disk."""
    parser = argparse.ArgumentParser(prog=prog, description=description)
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=Path.cwd() / default_dest_name,
        help=f"Destination directory (default: ./{default_dest_name}).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the destination directory if it already exists.",
    )
    args = parser.parse_args()

    dest: Path = args.output
    if dest.exists():
        if not args.force:
            print(
                f"error: {dest} already exists. "
                f"Pass --force to overwrite, or -o PATH to choose a different path.",
                file=sys.stderr,
            )
            return 1
        if dest.is_dir():
            shutil.rmtree(dest)
        else:
            dest.unlink()

    dest.parent.mkdir(parents=True, exist_ok=True)
    with as_file(files(package)) as src:
        shutil.copytree(
            src,
            dest,
            ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc", "__init__.py", "core", "*.core",
            ),
        )
    print(f"wrote {dest}")
    return 0
