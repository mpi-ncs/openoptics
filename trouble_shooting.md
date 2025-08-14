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

To resolve these issues, run the initialization script:

```bash
cd openoptics
bash ./openoptics/dashboard/init.sh
``
