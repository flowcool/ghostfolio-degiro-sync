# Download integrity and hash-lock evaluation

The Dockerfile retains version and SHA256 pins for Supercronic and Bitwarden on
amd64/arm64. Both curl calls restrict initial and redirected transfers to HTTPS
and require TLS 1.2 or newer. TLS verification and checksum verification remain
enabled. The extra redirect restriction prevents a release redirect from
downgrading transport; TLS flags do not replace artifact integrity checks.
The [curl manual](https://curl.se/docs/manpage.html) defines `--proto`,
`--proto-redir` and the minimum-version semantics of `--tlsv1.2`.

## Python hash locking

`requirements.txt` already pins direct and transitive versions. Pip's
`--require-hashes` additionally requires archive hashes for every requirement;
pinning alone does not enable it. The installed pip help and its hash-error
implementation confirm missing hashes and unpinned requirements are rejected.
See [pip secure installs](https://pip.pypa.io/en/stable/topics/secure-installs/).
Existing installed-package files are not authoritative wheel archives and cannot
be used to invent those hashes.

The public PyPI metadata for `degiro-connector==3.0.36` contains two release
archives; its wheel SHA256 matches [connector provenance](connector-provenance.yaml).
That verifies this one artifact, not the complete dependency lock or both native
platforms. Hashes fetched from the same index establish repeatability after
review; they do not independently establish publisher authenticity.

Recommend adopting hash-required, wheel-only runtime installation in a separate
maintenance change that includes deterministic lock regeneration and native
Python 3.12 amd64/arm64 resolution. Include every approved compatible wheel hash,
preserve the reviewed connector wheel pin, and keep dependency updates and hashes
atomic. Reject unavailable wheels rather than silently building sdists, which
would add a build-dependency and build-code trust boundary. Check how Dependabot
updates the lock: a version change retaining old hashes must fail, not bypass
integrity. Development requirements need their own compatible hash policy if
they include this runtime manifest.

Do not merely add `--require-hashes` to the current Dockerfile: this manifest has
no archive hashes, so clean builds would fail. This audit hardens binary transport
and evaluates the hash-lock migration; it does not claim to have generated or
validated the complete lock. Offline curl regressions prove non-HTTPS file
retrieval is refused with the actual download options; native container CI remains
the integration gate for real release downloads.
