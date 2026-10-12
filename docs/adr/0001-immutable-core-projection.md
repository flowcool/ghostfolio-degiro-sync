---
status: accepted
---

# Preserve the immutable broker-independent core projection

The DEGIRO adapter reuses a reviewed broker-independent implementation through
an immutable byte projection, with provenance and propagation owned by
[CORE_PROVENANCE.md](../../CORE_PROVENANCE.md). Keep broker policy, identities,
matching, authentication and bounded transport in the adapter instead of
hand-editing the projection or extracting a shared package through changes to
the canonical sibling: independent source ownership and explicit reviewed
propagation outweigh the convenience of a jointly evolving shared module.

This records the existing architecture, not a new propagation approval. The
adapter's sequential transport binding is part of that trade-off; a new
concurrency model requires its own design rather than reusing it implicitly.
