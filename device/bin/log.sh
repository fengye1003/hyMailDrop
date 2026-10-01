#!/bin/sh
# log.sh -- last 10 log lines to the screen, and the whole log stays on disk.
DIR=/mnt/us/extensions/hyMailDrop
LOG=$DIR/state/hyMailDrop.log
. $DIR/bin/banner.sh
# eips has no CJK glyphs on this device: strip the non-ASCII BYTES so the skeleton
# (timestamp / [OK] / HTTP codes / file names) still shows on screen.
i=1
tail -10 "$LOG" 2>/dev/null | tr -d '\200-\377' | while read -r line; do
    eips 1 $i "$(echo "$line" | cut -c1-46)"
    i=$((i+1))
done
echo "full log: $LOG"
tail -10 "$LOG" 2>/dev/null