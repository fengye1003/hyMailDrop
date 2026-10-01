#!/bin/sh
DIR=/mnt/us/extensions/hyMailDrop
STATE=$DIR/state
. $DIR/bin/banner.sh
rm -f $STATE/watch-on
sleep 1
pkill -f hyMailDrop.py 2>/dev/null
eips 1 1 "hyMailDrop: auto-sync OFF"
echo "auto-sync loop stopped"