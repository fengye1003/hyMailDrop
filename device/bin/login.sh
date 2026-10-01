#!/bin/sh
# login.sh -- device-code login, started DETACHED.
#
# Why detached: the poll can legally run for ~15 minutes (that is how long the user has to
# finish the browser step), and both KUAL and any remote caller would have given up long
# before that. So the code goes on the e-ink screen, this returns immediately, and the
# result lands in state/login.log.
# LF line endings only. ASCII only.
DIR=/mnt/us/extensions/hyMailDrop
STATE=$DIR/state
. $DIR/bin/banner.sh
mkdir -p $STATE
rm -f $STATE/login.log
setsid sh $DIR/bin/run.sh login < /dev/null >> $STATE/login.log 2>&1 &
sleep 4
eips 1 1 "hyMailDrop: code on screen"
eips 1 2 "or see state/login.log"
echo "login started (detached). code is on screen; log: $STATE/login.log"
