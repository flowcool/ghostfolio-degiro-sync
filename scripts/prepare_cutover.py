#!/usr/bin/env python3
"""Prepare an evidence-bound prospective manifest offline; no activation or HTTP."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import degiro_to_ghostfolio as adapter


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
    for name in ("broker", "destination", "mapping"):
        parser.add_argument("--" + name, required=True)
        parser.add_argument("--" + name + "-sha256", required=True)
    parser.add_argument("--source-account", required=True)
    parser.add_argument("--target-account", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        digest = prepare(args)
    except (RuntimeError, OSError, ValueError, KeyError, TypeError, yaml.YAMLError):
        print("Cutover preparation refused; opening evidence remains unchanged", file=sys.stderr)
        return 1
    print("CUTOVER_SHA256=" + digest)
    print("Opening contract verified; historical basis unverified; no activation or financial writes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
