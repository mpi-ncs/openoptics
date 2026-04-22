# Troubleshooting Guide

## Common Issues and Solutions

### Dashboard port already in use

`[Errno 98] Address already in use` when starting the dashboard usually means
a previous OpenOptics run didn't shut cleanly and its Uvicorn is still bound
to ``localhost:8001``. Options:

- Kill the leftover process: ``pkill -f 'openoptics-dashboard'`` or
  ``lsof -i :8001`` to find the PID.
- Pick a different port: ``export OPENOPTICS_DASHBOARD_PORT=8002`` before
  starting the example.

### Dashboard shows no epochs / empty sidebar

The SQLite database lives at ``~/.openoptics/dashboard.sqlite3`` (override
via ``$OPENOPTICS_STATE_DIR``). If you're running as ``root`` inside Docker
but the host's ``~/.openoptics`` is read-only, set
``OPENOPTICS_STATE_DIR=/tmp/openoptics`` for that run.

### ``ModuleNotFoundError: No module named 'fastapi'``

Install the dashboard extra: ``pip install "openoptics-dcn[dashboard]"``
(or ``[mininet]`` / ``[all]``, which pull it in transitively).
