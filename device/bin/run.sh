#!/bin/sh
# run.sh -- common entry point: pick a python, show the banner, run the plugin.
# LF line endings only. ASCII only.
DIR=/mnt/us/extensions/hyMailDrop
PY=/mnt/us/python3/bin/python3.9
[ -x "$PY" ] || PY=/usr/bin/python3
[ -x "$PY" ] || PY=/usr/bin/python
. $DIR/bin/banner.sh
exec "$PY" -u $DIR/bin/hyMailDrop.py "$@"