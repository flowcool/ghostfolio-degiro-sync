#!/usr/bin/env python3
"""Disposable runtime checks; no credentials, bind mounts or container network."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
import uuid


def run(*args, input_text=None, expected=0):
    result = subprocess.run(args, input=input_text, text=True, capture_output=True, timeout=30)
    if result.returncode != expected:
        raise RuntimeError(f"Container smoke command failed: {result.returncode}; {result.stdout}; {result.stderr}")
    return result.stdout + result.stderr


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image")
    args = parser.parse_args()
    options = ["docker", "run", "--rm", "--network=none", "--read-only",
               "--tmpfs", "/tmp:rw,nosuid,nodev,size=16m", "--cap-drop=ALL",
               "--security-opt=no-new-privileges"]
    expected = {}
    for line in Path("requirements.txt").read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            name, version = line.split("==")
            expected[name] = version
    core_hash = hashlib.sha256(Path("ghostfolio_core.py").read_bytes()).hexdigest()
    recovery_hash = hashlib.sha256(Path("scripts/recover_degiro.py").read_bytes()).hexdigest()
    provenance = Path("docs/connector-provenance.yaml").read_text()
    probe = f'''
import hashlib, importlib.metadata, json, os
from pathlib import Path
import yaml
import degiro_connector
import degiro_to_ghostfolio
from degiro_connector.trading.models.credentials import Credentials
assert os.getuid() == 10001
expected = {expected!r}
for name, version in expected.items():
    assert importlib.metadata.version(name) == version, name
assert {{"pytest", "pip-audit"}}.isdisjoint({{d.metadata["Name"].lower() for d in importlib.metadata.distributions()}})
assert hashlib.sha256(Path("/app/ghostfolio_core.py").read_bytes()).hexdigest() == {core_hash!r}
provenance = yaml.safe_load({provenance!r})
package = Path(degiro_connector.__file__).parent
files = sorted(package.rglob("*.py"))
tree = hashlib.sha256()
for path in files:
    name = "degiro_connector/" + path.relative_to(package).as_posix()
    tree.update(name.encode() + b"\\0" + path.read_bytes() + b"\\0")
assert len(files) == provenance["python_module_count"]
assert tree.hexdigest() == provenance["python_tree_sha256"]
assert not any(name.startswith(("DEGIRO_", "GHOST_TOKEN")) for name in os.environ)
assert sorted(p.name for p in Path("/app").iterdir()) == ["cash-rules.yaml", "degiro_to_ghostfolio.py", "entrypoint.sh", "ghostfolio_core.py", "requirements.txt", "scripts"]
assert sorted(p.name for p in Path("/app/scripts").iterdir()) == ["recover_degiro.py"]
assert hashlib.sha256(Path("/app/scripts/recover_degiro.py").read_bytes()).hexdigest() == {recovery_hash!r}
print("Runtime UID, dependency closure, source-equivalent connector, immutable core and explicit app file set: PASS")
'''
    print(run(*options, "-i", args.image, "python", "-", input_text=probe).strip())
    output = run(*options, args.image, expected=1)
    assert "Running once" in output and "DEGIRO sync failed" in output
    print("Default run-once fails closed without credentials: PASS")
    output = run(*options, args.image, "python", "/app/scripts/recover_degiro.py",
        "--expected-intent-id", "a" * 32, expected=1)
    assert "Positive import recovery failed" in output
    print("GET-only recovery refuses missing environment without mutation: PASS")
    for cron in ("* * * * *; echo unsafe", "* * * * *\necho unsafe", "@daily"):
        output = run(*options, "-e", f"CRON={cron}", args.image, expected=1)
        assert "Invalid CRON" in output
    print("Invalid/injected cron commands rejected: PASS")
    name = "degiro-smoke-" + uuid.uuid4().hex[:12]
    try:
        run(*options[:2], "-d", "--name", name, *options[3:], "-e", "CRON=* * * * *", args.image)
        deadline = time.monotonic() + 80
        while time.monotonic() < deadline:
            logs = run("docker", "logs", name)
            if "DEGIRO sync failed" in logs:
                assert "Running with validated cron schedule" in logs
                info = json.loads(run("docker", "inspect", name))[0]
                assert info["State"]["Running"] is True
                print("Actual minute cron invokes fail-closed job and remains running: PASS")
                break
            time.sleep(.25)
        else:
            raise RuntimeError("Cron did not invoke its job within the bounded smoke window")
    finally:
        subprocess.run(["docker", "rm", "-f", name], check=True, capture_output=True, timeout=15)


if __name__ == "__main__":
    main()
