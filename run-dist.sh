#!/bin/sh 

git pull

scp purd.me:ads-bby/config_terra_bella.json config.json

uv run main.py
