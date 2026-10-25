## Why

Historical comment maintenance rejects Ghostfolio versions other than 3.86.0.
It also requires one hard-coded upstream commit. These checks reject newer
targets before their operation evidence can be evaluated.

## What Changes

Accept semantic Ghostfolio versions at or above 3.86.0. Remove the fixed
upstream commit requirement. Keep the actual destination image and version
bound to the reviewed operation. Keep every financial and recovery control.

## Impact

The maintenance approval check, its offline regressions, the synchronization
specification and the recovery guide change. Normal synchronization, credentials
and transport permissions do not change. Source publication remains separate.
