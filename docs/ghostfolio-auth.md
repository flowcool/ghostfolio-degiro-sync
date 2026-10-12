# Ghostfolio authentication

Configure the final Ghostfolio origin and exactly one credential in the local ignored `.env` or an injected environment. The community Compose guide is in the root README.

| Variable | Meaning | Runtime behavior |
| --- | --- | --- |
| `GHOST_ACCESS_TOKEN` | Durable Ghostfolio Security Token | Exchange once per synchronization or authenticated recovery execution |
| `GHOST_TOKEN` | Legacy session bearer | Use unchanged; it expires and is not renewed |

Use the Security Token for unattended operation. Empty values count as absent; both nonempty credentials or neither block execution before network access. Recreate the container after changing its environment.

## Origin and transport

GHOST_HOST must be a complete origin without a trailing slash, path, userinfo, query or fragment. Valid HTTPS hostnames are configurable. Plain HTTP is limited to private/loopback IP addresses and single-label container hostnames. Link-local, unspecified and multicast addresses are refused. Transport pins each request to the exact configured origin and approved API paths; redirects are refused.

After local configuration and applicable journal checks, the adapter posts the Security Token to `/api/v1/auth/anonymous`. It accepts a nonempty printable ASCII `authToken` without spaces. It never logs either token, authentication responses or raw network exceptions. HTTP-library logging is muted during authentication and restored afterward. Ambient proxies, netrc and environment TLS overrides are disabled; TLS verification stays enabled. Connect/read timeouts are 10/30 seconds, without retries.

Failed authentication stops before broker and financial reads/writes. No token refresh occurs during financial work or after uncertain results. DRY_RUN allows this authentication POST and continues to block imports, cash updates and deletions.

For an approved HTTP origin, authentication exchange and bearer transport each
emit a fixed warning before use: credentials travel in cleartext without server
authentication. The warning includes no origin, token or account identifier.
A single-label hostname can resolve through host DNS/search domains to an
unintended machine; syntax validation does not prove local network ownership.
Prefer HTTPS, or restrict HTTP to an isolated trusted container network. The
Compose default remains supported; redirects and ambient proxies stay disabled.

## Provenance and recovery

The exchange reuses the reviewed IBKR v2.2.0 protocol at commit `54958ab1035eb97a1f67f9072b79699813ec3800`, outside the immutable core projection. See CORE_PROVENANCE.md for reviewed propagation.

Positive recovery is financial GET-only and preserves its separate local-confirmation gate. Neither authentication nor source rollback authorizes replay, deletion or financial corrections. Preserve journals and private captures when changing credentials or images.
