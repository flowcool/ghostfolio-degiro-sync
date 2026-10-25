# Design

## Context

`degiro.read_degiro` checks accounting before returning. Legacy cash-fund rows stop capture before saving. Keep that candidate unchanged.

## Goals / Non-Goals

Retain source evidence. No legacy import, filtered sync input or scheduled archive replay.

## Decisions

Mount `scripts/archive_degiro_history.py` read-only into the pinned image. Reuse its installed package, like `scripts/prepare_cutover.py`. Reuse `vault.broker_credentials`, `degiro.history_windows`, bounded transport, quiet logging and pinned vendor actions. No sibling or new credential mechanism.

Use one login and client discovery. Collect transactions/overview by window, current account/update evidence, bounded referenced products and optional locale-specific CSV. Do not call `read_degiro`, row merging or selection.

Capture eligible financial `response.content` bytes after HTTP decoding, before row interpretation. Never save authentication/client-discovery/logout bodies, URLs or headers. Parse UTF-8 JSON with duplicate-aware key inspection and depth bounds. Reject credential keys using the existing redaction vocabulary. CSV needs valid UTF-8 and an explicit credential-material check. Invalid encoding, unparseable JSON, sensitive material or oversized bodies produce metadata only and stop.

Record intent before dispatch. Require one response per collection intent. Preserve archive failures independently of vendor exception handling; `broker_call` already rejects None. Write response staging files exclusively, fsync, publish without replacement and fsync the directory. Then atomically publish the keyed YAML index. A crash may leave an orphan or pending entry; inspection reports both. No automatic resume/retry.

Limit each decoded body to16MiB, retained bodies to512MiB, product IDs to10000 and product requests to100. Clear inherited diagnostic accumulation after each request. Product extraction follows durable capture; invalid identifiers become findings. Existing transport buffers bodies before this limit; use an explicit container memory limit and do not claim a bounded download.

Offline inspection validates private regular basename-only files, sizes and hashes. Report per-response counts with offsets for flagged rows; conserve rows without merging overlap. Use excluded_legacy, malformed, unknown and unassessed. Index/report keep history_completeness_verified:false and import_status:archive_not_importable. requests_finished means only all requested steps returned.

## Risks / Trade-offs

Broker truncation remains unknown. Retain partial evidence on network/storage failure and attempt logout. Never certify completeness or accounting.

## Delivery and recovery

Use isolated synthetic tests and network-disabled pinned-image proof. Bind reviewed commit/hash, dates, private path, limits and credential source before real acquisition. Roll back source with Git revert. Retain archives; deletion and financial writes need separate authority.
