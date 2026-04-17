# Troubleshooting Guide

## Common Issues and Solutions

### Redis Connection Error
redis.exceptions.ConnectionError: Error 111 connecting to 127.0.0.1:6379. Connect call failed ('127.0.0.1', 6379).

### Database Table Missing Error
django.db.utils.OperationalError: no such table: dashboardapp_epochs

### Solution

These error messages indicate that either:
- The Redis server is not running
- The database has not been initialized

`BaseNetwork.start()` now runs Redis + Django migrations in-process whenever
`use_webserver=True`, so these should be rare. If you still see them, check
that `redis-server` is installed (`apt-get install redis-server`) and that
the dashboard log at `/tmp/openoptics_dashboard.log` doesn't show a Django
error.
