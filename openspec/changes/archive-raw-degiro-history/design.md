# Design

## Context

`degiro.read_degiro` merges history and checks accounting before returning. `accounting.merge_history` rejects legacy cash-fund records. The CLI saves afterward. Changing that path changes the candidate under qualification.

## Goals / Non-Goals

Retain evidence with the existing candidate. No legacy import or scheduled archive replay.

## Decisions

Mount `scripts/archive_degiro_history.py` read-only into the pinned image. Reuse its installed package, like `scripts/prepare_cutover.py`. No second credential mechanism.

Reuse `vault.broker_credentials`, `degiro.history_windows`, `bounded_broker_session`, `broker_call`, quiet logging and the pinned connector action APIs. Use one login and client discovery. Collect transactions and cash overview by window, then product metadata and current account/update evidence. Optional statement locale remains explicit. Do not call `read_degiro`, row-merging or financial selection. A separate archive operation cannot certify sync acceptance.

Wrap the bounded session response boundary to write permitted successful financial response bodies before the vendor action decodes them. Do not archive login, client-discovery or logout responses. Validate JSON structure for credential-field absence without changing saved bytes. Validate optional CSV encoding. Refuse credential-bearing bodies rather than rewriting them. Keep endpoint kinds and dates; discard URLs and headers.

Use exclusive private file creation and an atomic keyed YAML index. Record intent before each request, response hash after durable publication, and final collection status. Reuse private-file mechanisms from `app.save_private_snapshot` and migration journal publication, without altering them. A crash or failed index update leaves an incomplete archive; no resume or automatic retry is supported.

Add offline inspection to the same script. Verify archive hashes before reading rows. Identify each row by response and offset; do not merge overlapping windows. Report known legacy exclusions and malformed or unknown input with reasons. Keep other rows unassessed where full accounting evidence is absent. Report blocked import status, not a safe subset. Do not invoke financial writers or replace source bytes.

## Risks / Trade-offs

- Broker truncation is unknown → record requested ranges without claiming complete history.
- Legacy identifiers are unstable → preserve response boundaries and duplicate rows.
- Network or disk failure → retain partial evidence, stop and attempt logout.
- Real responses can contain personal financial data → private permissions, no raw logs, protected authentication boundary.

## Delivery and recovery

Prove synthetic transport and network-disabled pinned-image execution. Bind commit/hash, dates, private path and credential source in the approved operation. Source rollback is one Git revert. Recovery retains the archive; deletion, production changes and financial writes need separate authority.
