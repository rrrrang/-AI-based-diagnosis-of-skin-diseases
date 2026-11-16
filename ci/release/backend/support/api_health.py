"""Probe the actual API health route using only the standard library."""
import json
import urllib.request

with urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=2) as response:
    if response.status != 200 or json.load(response) != {"status": "ok"}:
        raise SystemExit(1)
