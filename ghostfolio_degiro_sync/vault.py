"""Fresh bounded vault retrieval; never log raw credentials."""

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from typing import Any

from ghostfolio_degiro_sync.config import validate_ghost_host
from ghostfolio_degiro_sync.diagnostics import tag_failure


def broker_credentials() -> Any:
    """Vault is the sole broker credential source for every execution."""
    from degiro_connector.trading.models.credentials import Credentials
    if any(name in os.environ for name in
           ("DEGIRO_USERNAME", "DEGIRO_PASSWORD", "DEGIRO_TOTP_SECRET")):
        raise tag_failure(RuntimeError("Direct DEGIRO credentials are unsupported; configure Bitwarden"),
                          "config", "direct_credentials")
    values = vault_broker_credentials()
    try:
        return Credentials(username=values[0], password=values[1], totp_secret_key=values[2])
    except Exception:
        raise tag_failure(RuntimeError("Invalid DEGIRO credentials"),
                          "config", "broker_credentials") from None


def vault_broker_credentials() -> tuple[str, str, str]:
    """Fresh isolated CLI state per execution; raw output never reaches logs."""
    stage = "configuration"
    try:
        names = ("BW_ITEM_ID", "BW_CLIENTID", "BW_CLIENTSECRET", "BW_PASSWORD")
        raw_values = {name: os.environ.get(name) for name in names}
        if any(not isinstance(value, str) or not value.strip() for value in raw_values.values()):
            raise ValueError
        values = {name: value for name, value in raw_values.items() if isinstance(value, str)}
        item_id = str(uuid.UUID(values.pop("BW_ITEM_ID")))
        if item_id != os.environ["BW_ITEM_ID"].lower():
            raise ValueError
        server = validate_ghost_host(os.environ.get("BW_SERVER", "https://vault.bitwarden.com"))
        if not server.startswith("https://"):
            raise ValueError
        stage = "temporary_state"
        deadline = time.monotonic() + 120
        with tempfile.TemporaryDirectory(prefix="degiro-vault-") as directory:
            os.chmod(directory, 0o700)
            environment = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL")
                           if key in os.environ}
            environment.update(values, BITWARDENCLI_APPDATA_DIR=directory,
                               BW_NOINTERACTION="true")

            def run(*arguments: str) -> str:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValueError
                result = subprocess.run(["/usr/local/bin/bw", *arguments],
                    env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, timeout=min(30, remaining), check=False)
                if result.returncode or len(result.stdout) > 2_000_000:
                    raise ValueError
                return result.stdout.decode()

            stage = "server"
            if server in ("https://bitwarden.com", "https://vault.bitwarden.com"):
                run("config", "server", "https://bitwarden.com")
            elif server in ("https://bitwarden.eu", "https://vault.bitwarden.eu"):
                run("config", "server", "https://vault.bitwarden.eu",
                    "--api", "https://api.bitwarden.eu", "--identity", "https://identity.bitwarden.eu")
            else:
                run("config", "server", server)
            stage = "login"
            run("login", "--apikey")
            try:
                stage = "unlock"
                session = run("unlock", "--passwordenv", "BW_PASSWORD", "--raw").strip()
                if not session or any(char.isspace() for char in session):
                    raise ValueError
                environment["BW_SESSION"] = session
                stage = "sync"
                run("sync")
                stage = "item"
                item = json.loads(run("get", "item", item_id))
                if (not isinstance(item, dict) or item.get("id") != item_id
                        or type(item.get("type")) is not int or item.get("type") != 1 or item.get("deletedDate")
                        or not isinstance(item.get("login"), dict)):
                    raise ValueError
                login = item["login"]
                credentials = [login.get(key) for key in ("username", "password", "totp")]
                if any(not isinstance(value, str) or not value.strip() for value in credentials):
                    raise ValueError
                import pyotp
                username, password, seed = (value for value in credentials if isinstance(value, str))
                seed = seed.strip()
                if seed.startswith("otpauth://"):
                    otp = pyotp.parse_uri(seed)
                    if (not isinstance(otp, pyotp.TOTP) or otp.interval != 30
                            or otp.digits != 6 or otp.digest != hashlib.sha1):
                        raise ValueError
                    seed = otp.secret
                seed = seed.upper()
                if not re.fullmatch(r"[A-Z2-7]{16,128}", seed):
                    raise ValueError
                base64.b32decode(seed + "=" * (-len(seed) % 8))
                return username, password, seed
            finally:
                previous_stage = stage
                # Cleanup must not replace the diagnostic of an earlier failure.
                stage = previous_stage if sys.exc_info()[0] is not None else "logout"
                run("logout")
                stage = previous_stage

    except Exception:
        raise tag_failure(RuntimeError("Bitwarden credential retrieval failed; no broker login attempted"),
                          "vault", stage) from None
