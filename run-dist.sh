#!/bin/sh 

## Allow the network to start up for a smidge longer.
echo "awaiting network"
sleep 5

git pull
scp <REMOTE_HOST>:path/to/config.json config.json

uv run main.py
