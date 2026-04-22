# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# Author: Yiming Lei (ylei@mpi-inf.mpg.de)
#
# License: Creative Commons NC BY SA 4.0
# https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en
"""Wipe dashboard history: SQLite DB + generated topology PNGs.

Usage::

    openoptics-dashboard-clean                 # prompts, then wipes everything
    openoptics-dashboard-clean --force         # no prompt
    openoptics-dashboard-clean --dry-run       # just report what would go
    openoptics-dashboard-clean --older-than 7d # keep only the last 7 days
    openoptics-dashboard-clean --state-dir /path/to/openoptics  # custom dir

Do not run while an OpenOptics script is active — the dashboard holds the
SQLite DB open and may recreate files after deletion.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path
from typing import Iterable, Optional, Tuple

_DURATION_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhd])\s*$", re.I)
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration(s: str) -> float:
    m = _DURATION_RE.match(s)
    if not m:
        raise argparse.ArgumentTypeError(
            f"invalid duration {s!r}; use e.g. 30m, 24h, 7d"
        )
    return float(m.group(1)) * _UNIT_SECONDS[m.group(2).lower()]


def _human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} {unit}"
        n /= 1024
    return f"{n} B"


def _iter_png_files(topos_dir: Path) -> Iterable[Path]:
    if not topos_dir.exists():
        return []
    return [p for p in topos_dir.iterdir() if p.is_file() and p.suffix == ".png"]


def _dir_png_summary(topos_dir: Path) -> Tuple[int, int]:
    files = list(_iter_png_files(topos_dir))
    return len(files), sum(f.stat().st_size for f in files)


def _prompt_yes(msg: str) -> bool:
    try:
        reply = input(f"{msg} [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return reply in ("y", "yes")


def _wipe_all(state_dir: Path, db_path: Path, topos_dir: Path,
              *, force: bool, dry_run: bool) -> int:
    n_png, sz_png = _dir_png_summary(topos_dir)
    db_size = db_path.stat().st_size if db_path.exists() else 0

    if not db_path.exists() and n_png == 0:
        print(f"Nothing to clean under {state_dir}.")
        return 0

    print(f"Would delete from {state_dir}:")
    if db_path.exists():
        print(f"  - {db_path}  ({_human_bytes(db_size)})")
    print(f"  - {topos_dir}/*.png  ({n_png} files, {_human_bytes(sz_png)})")

    if dry_run:
        return 0
    if not force and not _prompt_yes("Proceed?"):
        print("Aborted.")
        return 1

    if db_path.exists():
        db_path.unlink()
    for f in _iter_png_files(topos_dir):
        f.unlink()
    print(f"Deleted DB + {n_png} PNG files.")
    return 0


def _wipe_older_than(state_dir: Path, db_path: Path, topos_dir: Path,
                     *, older_than_s: float, force: bool, dry_run: bool) -> int:
    if not db_path.exists():
        print(f"No database at {db_path}, nothing to clean.")
        return 0

    # Late import so `--help` works without installing the dashboard extra.
    from openoptics.dashboard.storage.repository import Repository

    repo = Repository(db_path)
    try:
        cutoff = time.time() - older_than_s
        old_epochs = repo.list_epochs_older_than(cutoff)
        if not old_epochs:
            print("No epochs older than the cutoff; nothing to clean.")
            return 0

        old_ids = [e.id for e in old_epochs]
        orphan_pngs = [topos_dir / f"epoch_{i}.png" for i in old_ids]
        existing_pngs = [p for p in orphan_pngs if p.exists()]
        total_png_size = sum(p.stat().st_size for p in existing_pngs)

        print(f"Would delete {len(old_epochs)} epochs older than cutoff:")
        for e in old_epochs[:10]:
            print(f"  - [{e.id}] {e.display_name}")
        if len(old_epochs) > 10:
            print(f"  - ... and {len(old_epochs) - 10} more")
        print(
            f"Plus {len(existing_pngs)} PNG files "
            f"({_human_bytes(total_png_size)}) in {topos_dir}"
        )

        if dry_run:
            return 0
        if not force and not _prompt_yes("Proceed?"):
            print("Aborted.")
            return 1

        n_deleted = repo.delete_epochs(old_ids)
        for p in existing_pngs:
            p.unlink()
        print(f"Deleted {n_deleted} epochs and {len(existing_pngs)} PNG files.")
        return 0
    finally:
        repo.close()


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="openoptics-dashboard-clean",
        description=(
            "Wipe OpenOptics dashboard history: SQLite database + generated "
            "topology PNGs. Don't run while an OpenOptics script is active."
        ),
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Skip the confirmation prompt.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what would be deleted without modifying anything.",
    )
    parser.add_argument(
        "--older-than", type=parse_duration, default=None, metavar="DURATION",
        help=(
            "Only delete epochs older than DURATION (e.g. 30m, 24h, 7d). "
            "If omitted, wipes everything."
        ),
    )
    parser.add_argument(
        "--state-dir", type=Path, default=None, metavar="PATH",
        help=(
            "Override the dashboard state directory "
            "(defaults to $OPENOPTICS_STATE_DIR or ~/.openoptics)."
        ),
    )
    args = parser.parse_args(argv)

    from openoptics.dashboard.config import DashboardConfig

    cfg = DashboardConfig.from_env()
    if args.state_dir is not None:
        cfg.state_dir = args.state_dir

    db_path = cfg.db_path
    topos_dir = cfg.topos_dir

    if args.older_than is not None:
        return _wipe_older_than(
            cfg.state_dir, db_path, topos_dir,
            older_than_s=args.older_than,
            force=args.force, dry_run=args.dry_run,
        )
    return _wipe_all(
        cfg.state_dir, db_path, topos_dir,
        force=args.force, dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
