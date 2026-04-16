"""In-process dashboard bootstrap: Redis + Django migrations.

Called from ``BaseNetwork.start_monitor()`` so examples and tutorials just
work after ``pip install openoptics-dcn[dashboard]`` without a separate manual
``init.sh`` / CLI step. Paths are resolved via ``importlib`` so no
``/openoptics/...`` assumptions leak through.
"""
from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path


def start_redis() -> None:
    if shutil.which("pgrep") and subprocess.run(
        ["pgrep", "-x", "redis-server"], capture_output=True
    ).returncode == 0:
        return
    if shutil.which("service"):
        if subprocess.run(["service", "redis-server", "start"]).returncode == 0:
            return
    if shutil.which("redis-server"):
        subprocess.run(["redis-server", "--daemonize", "yes"], check=True)
        return
    raise RuntimeError(
        "redis-server not found. Install it (`apt-get install redis-server`) "
        "or use the ymlei/openoptics:latest Docker image, which has it preinstalled."
    )


def bootstrap() -> None:
    """Start Redis and apply dashboard DB migrations in-process."""
    start_redis()

    pkg = importlib.import_module("openoptics.dashboard")
    dashboard_root = str(Path(next(iter(pkg.__path__))))
    if dashboard_root not in sys.path:
        sys.path.insert(0, dashboard_root)

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
    from django.core.management import execute_from_command_line

    # Apply the migrations shipped with the package. We don't run
    # `makemigrations` here: migration files are authoring-time artifacts
    # that must be committed/bundled, not regenerated at runtime inside a
    # (potentially read-only) install location.
    execute_from_command_line(["manage.py", "migrate"])
