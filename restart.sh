#! /bin/bash

echo "Restarting $1logbot"
pkill -f " -n $1"
python3 logbot_roundrobin.py -f channels.txt &
