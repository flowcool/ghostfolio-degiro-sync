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

## CodeRabbit review

Review triggering is managed externally by Florent. Record missing, pending or
rate-limited coverage as a blocker; this template does not authorize a trigger.

- [ ] Verify that a review completed and covers the final PR head; a walkthrough,
      summary, skipped notice or rate-limit notice alone is not review evidence.
- [ ] Address confirmed findings and record the review link and reviewed head SHA.

After another push, verify completed coverage of the new final head.
Do not treat CodeRabbit as a substitute for CI or the repository's required
independent review.

Review evidence: <!-- completed review URL and reviewed commit SHA -->

Before merging, run `.venv/bin/python scripts/check_pr_merge.py <number>`.
The read-only preflight checks submitted final-head CodeRabbit review evidence,
required CI, review status, complete conversations and GitHub eligibility, then
rechecks the head. Use its returned SHA with `gh pr merge --match-head-commit`.
It performs no merge, comment, resolution or review trigger and grants no
production authority. GitHub remains authoritative at the actual merge.
The conservative helper does not accept comment-only legacy reviews or automate
an operator-approved review-reuse exception; it has no bypass flag.
