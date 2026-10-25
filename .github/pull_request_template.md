## Summary

<!-- Smallest useful diff sketch, diagram or brief overview. -->

## Behavior

Describe the problem and resulting behavior. Keep this PR focused on one change.

## Release impact

<!-- Version bump (none/patch/minor/major), breaking or operational change,
migration steps, rollback. Write "None" if there is no impact. Required, in
plain words, when the PR is labeled breaking-change or compat. -->

## Evidence

- Before:
- After:

## Verification

- Command:
- Expected result:
- Observed result:

Use synthetic inputs and isolated state. Do not attach secrets or private data.

## Merge Danger

- Door: <!-- one-way or two-way; exact rollback -->
- Blast Radius: <!-- smallest affected scope -->

## AI assistance

State whether AI assisted this change and what the author verified.

## Pullfrog review

- [ ] Completed Pullfrog review covers the exact final head.
- [ ] Actionable threads are resolved and all CI checks pass.

Review evidence: <!-- review URL and full reviewed SHA -->

CodeRabbit is not used. A sticky `pullfrog-approval` status alone does not block
merge. Every other CI check must pass. Docs-only changes (`openspec/`, `docs/`
or `*.md`) need CI and resolved conversations only.

Use `.venv/bin/python scripts/check_pr_merge.py <number>` for read-only
inspection. Use `.venv/bin/python scripts/merge_pr.py <number>` to merge.
The versioned helper requires fresh final-head evidence, verifies branch merge
policy, pins the evaluated head with `--match-head-commit` and offers no admin or auto-merge bypass.
After a failed or uncertain merge, inspect GitHub before any retry.
