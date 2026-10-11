#!/usr/bin/env python3
"""Synthetic provider fixture; all subprocess and child boundaries are mocked."""
import os
import subprocess
import sys
from pathlib import Path

STORE = Path(__file__).resolve().with_name("synthetic-vault-input")
KEYS = {"BW_CLIENTID", "BW_CLIENTSECRET", "BW_PASSWORD", "BW_ITEM_ID"}

def main():
    command = ["synthetic-secret-provider"]
    try:
        result = subprocess.run(command, input=STORE.read_bytes(), capture_output=True, timeout=60)
        if result.returncode:
            raise ValueError()
        values = dict(line.split("=", 1) for line in result.stdout.decode().splitlines() if line)
        if set(values) != KEYS or any(not value for value in values.values()):
            raise ValueError()
    except Exception:
        sys.stderr.write("DEGIRO credential loading failed; details suppressed.\n")
        return 1
    if sys.argv[1:] == ["--check"]:
        print("Vault environment fields present")
        return 0
    if len(sys.argv) < 2:
        sys.stderr.write("Usage: synthetic-loader.py --check | COMMAND [ARG ...]\n")
        return 2
    env = os.environ.copy()
    env.update(values)
    os.execvpe(sys.argv[1], sys.argv[1:], env)

if __name__ == "__main__":
    sys.exit(main())
