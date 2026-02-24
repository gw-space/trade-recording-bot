#!/bin/zsh
cd /Users/test/AIassistant
source /Users/test/AIassistant/.venv/bin/activate
exec python /Users/test/AIassistant/main.py >> /Users/test/AIassistant/bot.log 2>&1
