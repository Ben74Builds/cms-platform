#!/bin/bash
# If CONFIG_FILE is set, symlink it as config.py so the app picks it up
if [ -n "$CONFIG_FILE" ] && [ -f "/app/$CONFIG_FILE" ]; then
    cp "/app/$CONFIG_FILE" /app/config.py
    echo "[entrypoint] Using config: $CONFIG_FILE"
fi

exec python customer_side/main_stream_replay_from_postgres_to_kafka.py "$@"
