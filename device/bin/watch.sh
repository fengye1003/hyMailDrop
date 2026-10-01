#!/bin/sh
# watch.sh [interval-seconds] -- start the while-awake auto-sync loop, detached.
DIR=/mnt/us/extensions/hyMailDrop
STATE=$DIR/state
. $DIR/bin/banner.sh
mkdir -p $STATE
touch $STATE/watch-on
# detached: never hang the loop off the caller's pipes (see hyKBridge's restart.sh gotcha)
setsid sh $DIR/bin/watch-loop.sh "${1:-900}" < /dev/null >> $STATE/watch.log 2>&1 &
sleep 2
eips 1 1 "hyMailDrop: auto-sync ON"
eips 1 2 "every ${1:-900}s while awake"
echo "auto-sync loop started (every ${1:-900}s while the device is awake)"