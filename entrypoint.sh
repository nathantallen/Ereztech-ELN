#!/bin/sh
set -e
python -m app.init_db
exec gunicorn --bind 0.0.0.0:8000 --workers 2 "app:create_app()"
