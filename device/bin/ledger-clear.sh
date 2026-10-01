#!/bin/sh
# ledger-clear.sh -- forget what has already been delivered (next sync re-fetches history).
DIR=/mnt/us/extensions/hyMailDrop
. $DIR/bin/banner.sh
sh $DIR/bin/run.sh ledger --clear