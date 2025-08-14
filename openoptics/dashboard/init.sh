service redis-server start
python3 /openoptics/openoptics/dashboard/manage.py makemigrations dashboardapp
python3 /openoptics/openoptics/dashboard/manage.py migrate
