# Bitwarden CLI OSS distribution

The runtime image includes the official OSS Bitwarden CLI 2026.9.1 as a separate executable.
It is invoked through subprocesses; its source is not incorporated into the Python adapter.

- Release and architecture-specific binaries: https://github.com/bitwarden/clients/releases/tag/cli-v2026.9.1
- Corresponding source: https://github.com/bitwarden/clients/tree/cli-v2026.9.1
- Source archive: https://github.com/bitwarden/clients/archive/refs/tags/cli-v2026.9.1.tar.gz
- Build instructions: https://github.com/bitwarden/clients/blob/cli-v2026.9.1/apps/cli/README.md
- License: GNU GPL version 3, included as LICENSE.txt alongside this notice.

Dockerfile pins the release and verifies the official asset SHA256 separately for amd64 and arm64.
This notice and license are included in the image at /usr/local/share/bitwarden/.
