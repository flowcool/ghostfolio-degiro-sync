"""Run an isolated replay with one successful import acknowledgement lost.

Mount the synthetic replay driver at /lab/degiro_replay.py. This fault is at
the HTTP adapter boundary: the actual destination accepts the import before
the connector sees a transport failure. No broker transport is changed here.
"""
import os
import runpy
from urllib.parse import urlsplit
from unittest.mock import patch

import requests


def main():
    if os.environ.get("GHOST_HOST") != "http://ghostfolio:3333":
        raise SystemExit("Isolated lab destination required")
    original = requests.adapters.HTTPAdapter.send
    lost = False

    def send(adapter, request, **options):
        nonlocal lost
        response = original(adapter, request, **options)
        if (request.method == "POST" and urlsplit(request.url).path == "/api/v1/import"
                and 200 <= response.status_code < 300 and not lost):
            lost = True
            response.close()
            raise requests.ConnectionError("Synthetic lost import acknowledgement")
        return response

    with patch.object(requests.adapters.HTTPAdapter, "send", send):
        result = runpy.run_path("/lab/degiro_replay.py")["main"]()
    if not lost or result == 0:
        raise SystemExit("Expected uncertain import failure was not observed")
    print("LAB_FAULT: successful native import acknowledgement lost; connector stopped")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
