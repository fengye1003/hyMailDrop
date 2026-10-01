#!/bin/sh
# watch-loop.sh -- sync every N seconds WHILE THE DEVICE IS AWAKE.
#
# NOTE: this loop does not suspend and cannot wake the device. A sleeping Kindle cannot
# fetch mail by itself unless something wakes it -- see README "scheduling" for the three
# honest options. This one is simply "keep checking while I happen to be awake".
DIR=/mnt/us/extensions/hyMailDrop
STATE=$DIR/state
PY=/mnt/us/python3/bin/python3.9
[ -x "$PY" ] || PY=/usr/bin/python3
. $DIR/bin/banner.sh
INTERVAL=${1:-900}
while [ -f $STATE/watch-on ]; do
    "$PY" -u $DIR/bin/hyMailDrop.py sync --quiet
    sleep $INTERVAL
done