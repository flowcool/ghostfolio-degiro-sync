---
status: accepted
date: 2026-10-12
---

# Accept container credential co-location for unattended vault retrieval

Compose supplies `BW_CLIENTID`, `BW_CLIENTSECRET` and `BW_PASSWORD` through the
container environment. Docker administrators can read them through `docker
inspect`. Together they permit authentication and vault unlock, exposing the
selected DEGIRO username, password and TOTP seed. The two broker factors therefore
share one trust boundary; storing the seed in a vault does not preserve factor
separation against compromise of this container or its host.

Accept this deployment trade-off for unattended TOTP operation on an
operator-controlled host. Use a dedicated vault account containing only the
required item, restrict Docker/host/Portainer access, protect environment files
and backups, and rotate exposed credentials. Each run uses isolated temporary
CLI state, fresh retrieval, bounded subprocesses and secret-free diagnostics.
These controls limit exposure; they do not protect against a Docker administrator.

Docker secrets could reduce environment/inspect exposure, but file-based secret
loading is not currently supported: adding mounts alone will not work. Portainer
stack environment injection still ends in container environment variables;
Docker secrets managed through Portainer need the same reviewed loader work.
Neither protects broker factors once the process retrieves them. Direct broker
environment credentials are rejected; persistent unlocked CLI sessions would
widen exposure. Interactive approval or a separate human-held factor would
prevent unattended operation and is outside the supported flow.
