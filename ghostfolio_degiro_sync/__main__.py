"""Installed command; start the isolated worker before importing broker code."""

import sys

if sys.argv[1:] == ["--notify-worker"]:
    from ghostfolio_degiro_sync.notify import notify_worker
    raise SystemExit(notify_worker())

import runpy

runpy.run_module("degiro_to_ghostfolio", run_name="__main__")
