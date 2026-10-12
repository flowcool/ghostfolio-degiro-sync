# Security

Report suspected credential leaks or security vulnerabilities privately using
[GitHub private vulnerability reporting](https://github.com/flowcool/ghostfolio-degiro-sync/security/advisories/new).
Do not include DEGIRO credentials, TOTP secrets, session identifiers, Ghostfolio
tokens, account identifiers or real transaction exports in public issues or pull
requests.

Security fixes target the current `main` branch. Older revisions do not receive
separate backports. Dependency and container checks run on pull requests. Published amd64/arm64
images are available on GHCR; see the root README for the supported setup and
`.github/BUILD.md` for release checks. Publication does not
deploy the image or authorize financial writes.
