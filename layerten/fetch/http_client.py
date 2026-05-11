"""Process-level shared httpx clients for GitHub REST and GraphQL."""
from __future__ import annotations

import threading

import httpx

from layerten import config

_lock = threading.Lock()
_graphql_client: httpx.Client | None = None
_rest_client: httpx.Client | None = None


def _timeout() -> httpx.Timeout:
    s = float(getattr(config, "GITHUB_HTTP_TIMEOUT_S", 60))
    return httpx.Timeout(s)


def get_graphql_client() -> httpx.Client:
    global _graphql_client
    with _lock:
        if _graphql_client is None or _graphql_client.is_closed:
            _graphql_client = httpx.Client(
                timeout=_timeout(),
                headers={"Accept": "application/json"},
                follow_redirects=True,
            )
        return _graphql_client


def get_rest_client() -> httpx.Client:
    global _rest_client
    with _lock:
        if _rest_client is None or _rest_client.is_closed:
            _rest_client = httpx.Client(
                timeout=_timeout(),
                follow_redirects=True,
            )
        return _rest_client


def close_clients() -> None:
    """Close shared clients (optional; process exit is fine without)."""
    global _graphql_client, _rest_client
    with _lock:
        if _graphql_client is not None and not _graphql_client.is_closed:
            _graphql_client.close()
        if _rest_client is not None and not _rest_client.is_closed:
            _rest_client.close()
        _graphql_client = None
        _rest_client = None
