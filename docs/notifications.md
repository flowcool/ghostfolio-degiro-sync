# Failure notifications

The runtime includes Apprise. A separate Apprise server is optional; configure a
JSON list in APPRISE_URLS with destination URLs supported by Apprise. Empty or
invalid configuration disables notification; APPRISE_TIMEOUT bounds the isolated
worker to 1–30 seconds (default10). URLs are credentials and stay private.

Each failed scheduled synchronization sends at most one sanitized alert, including
scheduled DRY_RUN. Failed live synchronization also alerts in manual mode. Successful
runs, manual simulations and read-only captures are silent. Delivery failure never
changes the original failure exit status and never retries recursively. Unknown
errors map to a fixed generic reason; raw exception strings and account data are
not included. Notifications are nonfinancial outbound operations, even in DRY_RUN.

## Isolated verification

Contributors run `pytest -q tests/test_notify.py` inside their development environment.
It supplies synthetic URL/credential sentinels, mocks HTTP and uses the actual
Apprise worker to verify delivered/unreachable destinations, bounded expanded
URLs and secret-free failures. The scheduled-run cases use fake synchronization
results and exceptions; they never contact a real vault, broker, Ghostfolio or
notification recipient. The full offline suite separately verifies financial
write blocking. Production delivery tests require operator authorization.
