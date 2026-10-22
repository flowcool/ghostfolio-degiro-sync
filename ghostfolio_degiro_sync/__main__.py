"""Installed command; worker starts before the app or broker is imported."""

import logging
import sys

if sys.argv[1:] == ["--notify-worker"]:
    from ghostfolio_degiro_sync.notify import notify_worker
    raise SystemExit(notify_worker())

from ghostfolio_degiro_sync.app import main

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
raise SystemExit(main(sys.argv[1:]))
