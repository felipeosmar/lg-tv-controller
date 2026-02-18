#!/bin/bash
cd /home/felipe/work/lg-tv-controller
source venv/bin/activate
# Load .env if exists
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi
exec python app.py
