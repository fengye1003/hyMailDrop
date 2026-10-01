#!/bin/sh
# status.sh -- run status; the plugin itself puts the ASCII summary on the e-ink screen
# (eips on this device has no CJK glyphs, so the Chinese log stays in the file).
DIR=/mnt/us/extensions/hyMailDrop
. $DIR/bin/banner.sh
sh $DIR/bin/run.sh status --quiet
echo "full log: $DIR/state/hyMailDrop.log"