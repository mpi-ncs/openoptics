# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# Author: Yiming Lei (ylei@mpi-inf.mpg.de)
#
# License: Creative Commons NC BY SA 4.0
# https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en
"""One-shot installer for the ns-3 backend's native dependency.

Usage::

    openoptics-install-ns3                      # clone + build into ~/ns-3-dev
    openoptics-install-ns3 /opt/ns-3-dev        # pick the target directory
    openoptics-install-ns3 --skip-clone PATH    # use an existing ns-3 checkout
    openoptics-install-ns3 --dry-run PATH       # print planned commands only
    openoptics-install-ns3 --print-env-only     # just print the shell exports

The helper:

1. Clones the pinned vanilla ns-3 release (default ``ns-3.44``) into the given
   directory, unless ``--skip-clone`` is passed.
2. Symlinks the installed ``openoptics/backends/ns3/src/`` into
   ``<ns3_dir>/contrib/openoptics`` so ``./ns3 build`` discovers it as a
   standard ns-3 contrib module.
3. Runs ``./ns3 configure --enable-python-bindings --enable-examples`` and
   ``./ns3 build``.
4. Prints the two shell exports the backend needs at runtime.

Only the Python standard library is used; this script is safe to invoke from a
minimal ``pip install 'openoptics-dcn[ns3]'``.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Sequence

DEFAULT_NS3_VERSION = "ns-3.44"
DEFAULT_NS3_REPO = "https://gitlab.com/nsnam/ns-3-dev.git"
DEFAULT_NS3_DIR = Path("~/ns-3-dev").expanduser()
CONTRIB_LINK_NAME = "openoptics"
ENV_CONFIG_BASENAME = "ns3_env.json"


def _state_dir() -> Path:
    """Match the dashboard's `$OPENOPTICS_STATE_DIR` default (`~/.openoptics`)."""
    raw = os.environ.get("OPENOPTICS_STATE_DIR")
    return Path(raw).expanduser() if raw else (Path.home() / ".openoptics")


def env_config_path() -> Path:
    """Where the install helper records the chosen NS3_DIR for the backend
    to find. Reading this fallback is what lets a user run
    `python3 examples/...` without exporting NS3_DIR / PYTHONPATH first.
    """
    return _state_dir() / ENV_CONFIG_BASENAME


def _src_dir() -> Path:
    """Location of the contrib module shipped with this package."""
    return (Path(__file__).resolve().parent / "src").resolve()


def _run(cmd: Sequence[str], cwd: Optional[Path] = None, *, dry_run: bool) -> None:
    pretty = " ".join(str(c) for c in cmd)
    prefix = f"(cd {cwd} && " if cwd else ""
    suffix = ")" if cwd else ""
    print(f"$ {prefix}{pretty}{suffix}")
    if dry_run:
        return
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def _emit_env_lines(ns3_dir: Path) -> None:
    """Emit *only* shell-eval-safe export lines.

    Used by ``--print-env-only`` so that
    ``eval $(openoptics-install-ns3 --print-env-only PATH)`` sets the
    env without choking on prose. Values are shell-quoted with
    ``shlex.quote``; the ``${PYTHONPATH:-}`` default-expansion stays
    literal so the shell expands it (rather than Python).
    """
    quoted_dir = shlex.quote(str(ns3_dir))
    quoted_py = shlex.quote(f"{ns3_dir}/build/bindings/python")
    print(f"export NS3_DIR={quoted_dir}")
    print(f'export PYTHONPATH={quoted_py}:"${{PYTHONPATH:-}}"')


def _print_env(ns3_dir: Path, config_path: Path, wrote_config: bool) -> None:
    """Human-facing env instructions.

    Once ``ns3_env.json`` is written the backend auto-discovers ns-3 on
    import, so the shell exports become optional — only needed if the
    user wants ``from ns import ns`` to work in unrelated Python sessions
    or scripts that don't go through ``Ns3Backend``.
    """
    print()
    if wrote_config:
        print(f"Recorded NS3_DIR in {config_path}.")
        print(
            "The ns-3 backend will pick this up automatically — running "
            "`python3 examples/ns3_*.py` now Just Works."
        )
        print()
        print(
            "Optional: also add these to your shell (~/.bashrc or "
            "equivalent) if you want to import `ns` directly outside the "
            "backend, or override the recorded path:"
        )
    else:
        print("Add these to your shell (~/.bashrc or equivalent):")
    _emit_env_lines(ns3_dir)


def _clone(ns3_dir: Path, repo: str, version: str, *, dry_run: bool) -> None:
    if ns3_dir.exists() and any(ns3_dir.iterdir()):
        print(f"Target {ns3_dir} already exists and is non-empty; skipping clone.")
        print("Pass --skip-clone to suppress this message, or remove the directory.")
        return
    ns3_dir.parent.mkdir(parents=True, exist_ok=True)
    _run(
        ["git", "clone", "--depth", "1", "--branch", version, repo, str(ns3_dir)],
        dry_run=dry_run,
    )


def _link_contrib(ns3_dir: Path, *, dry_run: bool) -> None:
    src = _src_dir()
    if not src.exists() and not dry_run:
        raise RuntimeError(
            f"Contrib source directory not found at {src}. "
            "Is openoptics installed correctly?"
        )

    contrib_dir = ns3_dir / "contrib"
    target = contrib_dir / CONTRIB_LINK_NAME

    if target.exists() or target.is_symlink():
        # A symlink pointing at our src/ is already idempotent; anything else
        # belongs to the user and we refuse to stomp it.
        if target.is_symlink() and target.resolve() == src:
            print(f"Symlink {target} -> {src} already in place.")
            return
        raise RuntimeError(
            f"{target} already exists and does not point at {src}. "
            "Remove it manually (or use a different --ns3-dir) and rerun."
        )

    print(f"$ ln -s {src} {target}")
    if not dry_run:
        contrib_dir.mkdir(parents=True, exist_ok=True)
        os.symlink(src, target)


def _write_env_config(ns3_dir: Path, *, dry_run: bool) -> bool:
    """Persist the chosen NS3_DIR so the backend can pick it up without
    requiring shell exports.  Idempotent — overwrites silently.
    """
    config_path = env_config_path()
    print(f"$ write {config_path} (ns3_dir={ns3_dir})")
    if dry_run:
        return False
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps({"ns3_dir": str(ns3_dir)}, indent=2) + "\n"
        )
    except OSError as e:
        # Don't fail the install for an unwritable state dir; user can
        # still fall back to manual exports.
        print(f"Warning: could not write {config_path}: {e}", file=sys.stderr)
        return False
    return True


def _check_build_tools(*, need_git: bool, need_build: bool, dry_run: bool) -> None:
    needed: List[str] = []
    if need_git:
        needed.append("git")
    if need_build:
        needed.extend(("cmake", "g++"))
    missing = [tool for tool in needed if shutil.which(tool) is None]
    if missing and not dry_run:
        raise RuntimeError(
            f"Missing required build tools: {', '.join(missing)}. "
            "On Debian/Ubuntu: sudo apt install git g++ cmake python3-dev "
            "python3-setuptools libgsl-dev libxml2-dev pkg-config"
        )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="openoptics-install-ns3",
        description=(
            "Build ns-3 with the OpenOptics contrib module linked in. "
            "Prints the NS3_DIR / PYTHONPATH exports the Ns3Backend needs."
        ),
    )
    parser.add_argument(
        "ns3_dir",
        nargs="?",
        type=Path,
        default=DEFAULT_NS3_DIR,
        help=f"Where to clone/build ns-3 (default: {DEFAULT_NS3_DIR}).",
    )
    parser.add_argument(
        "--ns3-version",
        default=DEFAULT_NS3_VERSION,
        help=(
            f"ns-3 git tag to clone (default: {DEFAULT_NS3_VERSION}). "
            "Floor is ns-3.37 — earlier releases predate cppyy-based Python "
            "bindings and are not supported."
        ),
    )
    parser.add_argument(
        "--ns3-repo",
        default=DEFAULT_NS3_REPO,
        help=f"ns-3 git repo URL (default: {DEFAULT_NS3_REPO}).",
    )
    parser.add_argument(
        "--skip-clone",
        action="store_true",
        help="Use an existing ns-3 checkout at ns3_dir; skip the git clone step.",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Link the contrib module but don't run ./ns3 configure/build.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print every command that would be executed, without running them.",
    )
    parser.add_argument(
        "--print-env-only",
        action="store_true",
        help=(
            "Print the NS3_DIR / PYTHONPATH exports for the given ns3_dir and "
            "exit. Useful for shell-eval (`eval $(openoptics-install-ns3 "
            "--print-env-only PATH)`)."
        ),
    )
    args = parser.parse_args(argv)

    ns3_dir = args.ns3_dir.expanduser().resolve() if args.ns3_dir.exists() \
        else args.ns3_dir.expanduser()

    if args.print_env_only:
        # Shell-eval-safe output: exports only, no prose header.
        _emit_env_lines(ns3_dir)
        return 0

    try:
        _check_build_tools(
            need_git=not args.skip_clone,
            need_build=not args.skip_build,
            dry_run=args.dry_run,
        )

        if not args.skip_clone:
            _clone(ns3_dir, args.ns3_repo, args.ns3_version, dry_run=args.dry_run)
        elif not ns3_dir.exists() and not args.dry_run:
            raise RuntimeError(
                f"--skip-clone was passed but {ns3_dir} does not exist."
            )

        _link_contrib(ns3_dir, dry_run=args.dry_run)

        if not args.skip_build:
            _run(
                ["./ns3", "configure", "--enable-python-bindings", "--enable-examples"],
                cwd=ns3_dir,
                dry_run=args.dry_run,
            )
            _run(["./ns3", "build"], cwd=ns3_dir, dry_run=args.dry_run)
    except subprocess.CalledProcessError as e:
        print(f"\nCommand failed with exit code {e.returncode}: {e.cmd}", file=sys.stderr)
        return e.returncode or 1
    except RuntimeError as e:
        print(f"\nError: {e}", file=sys.stderr)
        return 1

    wrote_config = _write_env_config(ns3_dir, dry_run=args.dry_run)
    _print_env(ns3_dir, env_config_path(), wrote_config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
