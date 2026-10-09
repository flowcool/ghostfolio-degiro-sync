#!/usr/bin/env python3
"""Load encrypted DEGIRO credentials into a child environment without a shell."""
import os
import subprocess
import sys
from pathlib import Path

STORE = Path(__file__).resolve().with_name("access-degiro.local.env")
KEYS = {"DEGIRO_USERNAME", "DEGIRO_PASSWORD", "DEGIRO_TOTP_SECRET"}

def main():
    command = ["docker", "run", "--rm", "-i", "-u", str(os.getuid()) + ":" + str(os.getgid()),
               "-v", "/etc/komodo-secrets/age-agentvm.key:/k:ro", "-e", "SOPS_AGE_KEY_FILE=/k",
               "ghcr.io/getsops/sops:v3.13.3", "decrypt", "--input-type", "dotenv",
               "--output-type", "dotenv", "/dev/stdin"]
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
        print("DEGIRO_USERNAME_present=True DEGIRO_PASSWORD_present=True DEGIRO_TOTP_SECRET_present=True")
        return 0
    if len(sys.argv) < 2:
        sys.stderr.write("Usage: run-degiro-env.py --check | COMMAND [ARG ...]\n")
        return 2
    env = os.environ.copy()
    env.update(values)
    os.execvpe(sys.argv[1], sys.argv[1:], env)

if __name__ == "__main__":
    sys.exit(main())
