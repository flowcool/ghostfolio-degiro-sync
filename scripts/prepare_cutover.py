#!/usr/bin/env python3
"""Capture and validate a prospective cutover, or validate existing evidence offline."""
import argparse
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import hashlib
import json
import os
from pathlib import Path
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import degiro_to_ghostfolio as adapter


def capture(output, config, from_date=None):
    if config["dry_run"] is not True:
        raise RuntimeError("Cutover capture requires DRY_RUN")
    today = datetime.now(ZoneInfo("Europe/Zurich")).date()
    start = date.fromisoformat(from_date) if from_date else today - timedelta(days=1)
    adapter.history_windows(start, today)  # Validate before publication or login.
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
    broker = adapter.read_degiro(start, today,
        report_locale=("fr", "fr"), holdings=True, cutover_target_reader=destination)
    target = broker.pop("opening_destination")
    adapter.save_private_snapshot(broker, paths["broker"])
    adapter.save_private_snapshot(target, paths["destination"], compact=True)
    return paths


def prepare(args):
    captures, bindings = {}, {}
    for name in ("broker", "destination"):
        path = Path(getattr(args, name)).absolute()
        digest = getattr(args, name + "_sha256")
        raw = adapter.read_private_evidence(path, digest)
        captures[name] = json.loads(raw, object_pairs_hook=adapter.unique_evidence_pairs)
        bindings[name] = {"path": str(path), "sha256": digest}
    mapping_raw = adapter.read_private_evidence(args.mapping, args.mapping_sha256)
    mapping, quotes = adapter.verified_mapping_document(yaml.safe_load(mapping_raw))
    manifest = {"version": 1, "source_account": args.source_account,
        "target_account": args.target_account, "cutover": captures["broker"]["fetched_at"],
        "mapping_sha256": adapter.evidence_digest({"mapping": mapping, "quote_currencies": quotes}),
        "opening": bindings, "basis_status": "unverified"}
    adapter.prospective_opening_context({"manifest": manifest, "captures": captures},
        {"source_account": args.source_account, "target_account": args.target_account}, mapping, quotes)
    destination = adapter.snapshot_destination(args.output)
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    raw = yaml.safe_dump(manifest, sort_keys=True).encode()
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(raw).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--output-directory")
    parser.add_argument("--from-date", help="Capture history start; defaults to yesterday (capture only)")
    for name in ("broker", "destination", "mapping"):
        parser.add_argument("--" + name)
        parser.add_argument("--" + name + "-sha256")
    parser.add_argument("--source-account")
    parser.add_argument("--target-account")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        if args.capture:
            if (not args.output_directory or any(getattr(args, name) is not None for name in (
                    "broker", "broker_sha256", "destination", "destination_sha256", "mapping",
                    "mapping_sha256", "source_account", "target_account", "output"))):
                raise RuntimeError("Invalid capture options")
            config, unused_mapping, unused_quotes = adapter.load_sync_config()
            paths = capture(args.output_directory, config, args.from_date)
            mapping_path = Path(os.environ.get("MAPPING_FILE", "mapping.yaml")).absolute()
            args = SimpleNamespace(
                broker=str(paths["broker"]), destination=str(paths["destination"]),
                broker_sha256=hashlib.sha256(paths["broker"].read_bytes()).hexdigest(),
                destination_sha256=hashlib.sha256(paths["destination"].read_bytes()).hexdigest(),
                mapping=str(mapping_path), mapping_sha256=hashlib.sha256(mapping_path.read_bytes()).hexdigest(),
                source_account=config["source_account"], target_account=config["target_account"],
                output=str(Path(args.output_directory).absolute() / "manifest.yaml"))
        elif (args.output_directory or args.from_date or not all(getattr(args, name) for name in (
                "broker", "broker_sha256", "destination", "destination_sha256", "mapping",
                "mapping_sha256", "source_account", "target_account", "output"))):
            raise RuntimeError("Missing offline evidence options")
        digest = prepare(args)
    except Exception as error:
        # Only fixed adapter diagnostics may cross the private capture boundary.
        stages = ("login", "client_discovery", "transactions", "account_overview", "products",
                  "account_info", "account_update", "account_report", "order_history", "cutover_destination")
        messages = {f"DEGIRO read failed at {stage}; no financial writes attempted" for stage in stages}
        messages.add("DEGIRO logout failed")
        messages.update(adapter.API_FORMAT_ERRORS.values())
        messages.update(f"DEGIRO login failed: {reason}" for reason in adapter.AUTH_FAILURE_REASONS)
        message = str(error)
        if message in messages:
            print(message, file=sys.stderr)
        print("Cutover preparation refused; retained evidence is not approval", file=sys.stderr)
        return 1
    print("CUTOVER_SHA256=" + digest)
    print("Opening contract verified; historical basis unverified; no activation or financial writes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
