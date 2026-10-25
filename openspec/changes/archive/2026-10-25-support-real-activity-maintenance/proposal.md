## Why

Real activity responses omit isDraft and advance the owned Order updatedAt on comment writes. The synthetic maintenance fixtures did not cover this API shape. The runtime image also omitted the explicit maintenance command.

## What Changes

Use draft/exclusion tags when isDraft is absent. Permit only the backend timestamp advance on the row just written, retain full postimages, and preserve strict checks on all other fields and protected rows. Include the explicit maintenance command in the runtime image.
