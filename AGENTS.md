# Repository working agreement

The supported user deployment is Docker Compose. README.md owns the complete setup and configuration guide. Keep public artifacts provider-portable and free of personal hosts, paths, operator identities and private work-tracker records.

## Architecture and invariants

- `degiro_to_ghostfolio.py` owns DEGIRO conversion, identities, matching, URL policy, vault retrieval and orchestration.
- `ghostfolio_core.py` is the immutable byte projection defined in CORE_PROVENANCE.md. Change the adapter, never hand-edit the projection or modify the canonical sibling from this project.
- Functional Python: module-level functions, no custom classes or type annotations. Every logic change has an offline regression.
- Runtime dependencies and downloaded binaries are pinned. Pytest and developer tools stay outside the runtime image.
- Credentials enter through environment variables; the configured vault item supplies broker credentials per execution. Use isolated temporary CLI state, bounded subprocesses and secret-free diagnostics. Broker credentials must come from the vault; direct DEGIRO credential variables are rejected.
- Read docs/ghostfolio-auth.md before changing authentication or transport. Keep exact credential exclusivity, one token exchange per execution, strict origins, no redirects and no raw response logging.
- DRY_RUN permits authentication and reads while blocking financial writes. Unknown or ambiguous relevant account data blocks dispatch. Preserve all accounting, identity, coverage and uncertain-result recovery guards.

## Validation and delivery

See CONTRIBUTING.md for developer commands. Run the full offline suite, core integrity, semantic diff, numstat and whitespace checks before committing. Synthetic tests and lab checks use disposable state without real vault, broker or production credentials.

Public bug reports and compatibility notices use GitHub Issues. Existing local work-tracker policy is supplied by the execution environment; do not publish private tracker IDs or paths.

For PR descriptions and merge execution, read `.github/pull_request_template.md`; use `scripts/merge_pr.py` for merges. Required CI and a completed CodeRabbit review must cover the exact final head. Review triggering is managed externally by maintainers; pending, skipped or rate-limited review is not evidence. Record the completed review URL and SHA before guarded merge. Source approval never authorizes production deployment or financial mutations.

Rollback source changes with an atomic Git revert. Preserve local journals and private captures. Runtime deployment, financial writes, cleanup and destructive recovery require the operator's explicit authorization.
