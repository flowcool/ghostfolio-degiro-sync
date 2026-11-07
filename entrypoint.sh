#!/bin/bash
set -eu

if [ "$#" -gt 0 ] && [[ "$1" != --* ]]; then
    exec "$@"
fi
if [ "$#" -eq 1 ] && [ "$1" = --notify-worker ]; then
    exec python -m ghostfolio_degiro_sync "$@"
fi

cat <<'BANNER'
+--------------------------------------+
|             DEGIRO SYNC              |
|         DEGIRO -> Ghostfolio         |
+--------------------------------------+
BANNER
version=${APP_VERSION:-dev}
revision=${APP_REVISION:-unknown}
if [[ ! "$version" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]; then version=dev; fi
if [[ ! "$revision" =~ ^[0-9a-f]{40}$ ]]; then revision=unknown; fi
printf 'ghostfolio-degiro-sync version %s — commit %s\n' "$version" "${revision:0:12}"

if [ "$#" -gt 0 ]; then
    exec python -m ghostfolio_degiro_sync "$@"
fi
if [ -n "${CRON:-}" ]; then
    # Five numeric cron fields only; never interpolate an environment command.
    if [[ ! "$CRON" =~ ^[0-9*/,-]+([[:blank:]][0-9*/,-]+){4}$ ]]; then
        echo 'Invalid CRON: expected five numeric schedule fields' >&2
        exit 1
    fi
    crontab_path="$(mktemp)"
    # Managed cron is local only: inherited Sentry must not enable Go HTTP.
    unset SENTRY_DSN SENTRY_ENVIRONMENT SENTRY_RELEASE
    printf '%s python -m ghostfolio_degiro_sync --sync\n' "$CRON" > "$crontab_path"
    supercronic -test "$crontab_path"
    echo 'Running with validated cron schedule'
    exec supercronic "$crontab_path"
fi
echo 'Running once'
exec python -m ghostfolio_degiro_sync --sync
