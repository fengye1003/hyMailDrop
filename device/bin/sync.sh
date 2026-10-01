#!/bin/sh
# sync.sh -- one sync pass: read the mailbox, drop new attachments into /documents.
DIR=/mnt/us/extensions/hyMailDrop
. $DIR/bin/banner.sh
sh $DIR/bin/run.sh sync