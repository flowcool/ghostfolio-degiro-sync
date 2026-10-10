#!/usr/bin/env python3
"""Capture candidate cutover evidence with bounded reads only; never activate sync."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import degiro_to_ghostfolio as adapter


def capture(output):
    config, mapping, quotes = adapter.load_sync_config()
    if config["dry_run"] is not True:
        raise RuntimeError("Cutover capture requires DRY_RUN")
    # Reject all pre-existing output before login; never replace original evidence.
    root = Path(output).resolve()
    paths = {name: adapter.snapshot_destination(root / (name + ".json"))
        for name in ("broker", "destination")}
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    def destination():
        target = {"id": config["target_account"], "currency": "EUR"}
        with adapter.ghost_transport(config, target) as session:
            response = session.get(config["ghost_host"] + "/api/v1/account/" + config["target_account"])
            response.raise_for_status()
            account = response.json()
            response = session.get(config["ghost_host"] + "/api/v1/activities")
            response.raise_for_status()
            body = response.json()
        return {"account": account, "activities": body,
            "captured_at": datetime.now(timezone.utc).isoformat()}
    today = datetime.now(ZoneInfo("Europe/Zurich")).date()
    broker = adapter.read_degiro(today - timedelta(days=1), today,
        report_locale=("fr", "fr"), holdings=True, cutover_target_reader=destination)
    target = broker.pop("opening_destination")
    adapter.save_private_snapshot(broker, paths["broker"])
    adapter.save_private_snapshot(target, paths["destination"])
    return paths


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", required=True)
    args = parser.parse_args(argv)
    try:
        paths = capture(args.output_directory)
        for name, path in paths.items():
            print(name.upper() + "_SHA256=" + hashlib.sha256(path.read_bytes()).hexdigest())
    except Exception:
        print("Read-only cutover capture failed; retained partial evidence is not approval", file=sys.stderr)
        return 1
    print("Candidate captures saved; prepare and pin the manifest, then validate a fresh DRY_RUN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
