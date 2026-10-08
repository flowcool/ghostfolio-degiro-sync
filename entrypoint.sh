#!/bin/bash
set -eu

if [ "$#" -gt 0 ]; then
    exec "$@"
fi

echo "ghostfolio-degiro-sync version ${APP_VERSION:-dev}"
if [ -n "${CRON:-}" ]; then
    # Five numeric cron fields only; never interpolate an environment command.
    if [[ ! "$CRON" =~ ^[0-9*/,-]+([[:blank:]][0-9*/,-]+){4}$ ]]; then
        echo 'Invalid CRON: expected five numeric schedule fields' >&2
        exit 1
    fi
    crontab_path="$(mktemp)"
    printf '%s python /app/degiro_to_ghostfolio.py --sync\n' "$CRON" > "$crontab_path"
    supercronic -test "$crontab_path"
    echo 'Running with validated cron schedule'
    exec supercronic "$crontab_path"
fi
echo 'Running once'
exec python /app/degiro_to_ghostfolio.py --sync
