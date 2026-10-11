# Ghostfolio authentication

Provide exactly one nonempty environment credential, backed by the off-git SOPS
store and host loader. Never pass values in argv, committed YAML or plaintext
dotenv files. Whitespace-only values count as absent; setting both nonempty
variables or neither refuses the operation before network access.

| Variable | Meaning | Runtime behavior |
| --- | --- | --- |
| `GHOST_ACCESS_TOKEN` | Durable Ghostfolio UI Security Token | Exchange once per sync, positive-recovery or cutover-capture execution |
| `GHOST_TOKEN` | Previously obtained session bearer | Use unchanged; no login or automatic renewal |

## Exchange and failure boundary

After local configuration/mapping/date and applicable journal/cutover checks,
the adapter posts `{"accessToken": "<security token>"}` to the exact approved
`GHOST_HOST` plus `/api/v1/auth/anonymous`. It accepts a nonempty printable ASCII
`authToken` without spaces as the bearer. Subsequent target requests use that
bearer; the Security Token is removed from runtime config and neither credential
is written into journals or captures.

The existing exact-origin policy remains authoritative: no URL credentials,
path prefix, query, fragment or arbitrary origin. Login uses a dedicated session
with ambient proxies, netrc and environment TLS overrides disabled; default TLS
certificate verification stays enabled. Connect/read inactivity timeouts are
10/30 seconds. Redirects and retries are disabled. The response body, security
token, bearer and raw request exceptions never enter application diagnostics.
HTTP library logs are muted during login, including DEBUG, then restored.

A rejected/redirected/timed-out login, invalid JSON or unusable bearer stops the
execution before broker or target reads and financial writes. The returned
bearer is not refreshed after a later 401 or an uncertain import. The next
explicit execution may authenticate again, subject to existing journal gates.
An invalid selected recovery intent refuses login before financial readback.

DRY_RUN allows the login POST because it changes authentication state only.
It continues to forbid financial imports, balance updates and deletions.
Positive recovery remains financial GET-only; its explicit local confirmation
gate does not authorize replay, broker access or financial mutation.

## Reuse and provenance

The exchange protocol, exclusive credential modes, response validation and fixed
error messages reuse `ghost_exchange_access_token`, `load_config` and their
dependencies from reviewed IBKR release v2.2.0, commit
`54958ab1035eb97a1f67f9072b79699813ec3800` of
[the canonical sibling](https://github.com/flowcool/ghostfolio-ibkr-sync/blob/54958ab1035eb97a1f67f9072b79699813ec3800/ibkr_to_ghostfolio.py).
The adapter adds DEGIRO's stricter exact-origin allowlist, isolated HTTP session,
muted library logs and recovery/capture integration. This is deliberate adapter
reuse, outside the byte projection: the immutable core, its manifest and the
sibling are unchanged. Upstream propagation still follows CORE_PROVENANCE.md.

## Infra provisioning, rotation and rollback

The broker loader continues to decrypt only its three existing DEGIRO keys;
infra supplies the independent Ghostfolio credential in the launcher's
environment. Compose passes both supported names without values. Docker
environment-name passing does not hide credentials from daemon operators;
protect container metadata and backups under the existing runtime contract.

For permanent cron, provision the UI Security Token as `GHOST_ACCESS_TOKEN` and
unset `GHOST_TOKEN`. The token is exchanged each execution, with no vault/SOPS
access inside the application container. A session bearer obtained from login
belongs only in legacy `GHOST_TOKEN`, not in the Security Token variable.
Existing lab bearer mode remains supported. Recreate the container through the
host loader after rotation or switching modes; restart alone retains its old
environment. Provisioning, rotation, cron activation and deployment remain infra
operations requiring their existing authorization. Financial import and live
reconciliation remain owned by the separately authorized rollout decision.

Rollback the scoped code commit and restore the previous `GHOST_TOKEN` launcher
contract with a still-valid bearer. Preserve credentials, private evidence and
journals. A code rollback does not revoke tokens or reverse financial records;
owned scheduling/image changes and financial compensation need their separate
operator authorization.
