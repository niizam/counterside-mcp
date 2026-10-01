"""Fixtures for comparing this server against a live Node Mod:Side API.

The whole directory skips when Mod:Side is not running, so the unit suite
stays runnable without Node, node_modules or the launcher.
"""

import json
import os
import urllib.parse
import urllib.request

import pytest

# Override with CS_MODSIDE_API when the launcher picked a different port.
BASE = os.environ.get("CS_MODSIDE_API", "http://127.0.0.1:5175/mod-side/api")


@pytest.fixture(scope="session")
def node_api():
    def reachable() -> bool:
        try:
            with urllib.request.urlopen(f"{BASE}/health", timeout=1.5) as response:
                return response.status == 200
        except Exception:
            return False

    if not reachable():
        pytest.skip(f"Mod:Side API is not running on {BASE}")

    def get(route: str, **params):
        query = "&".join(
            f"{key}={urllib.parse.quote(str(value))}" for key, value in params.items()
        )
        url = f"{BASE}/{route}" + (f"?{query}" if query else "")
        with urllib.request.urlopen(url, timeout=30) as response:
            return json.load(response)

    return get
