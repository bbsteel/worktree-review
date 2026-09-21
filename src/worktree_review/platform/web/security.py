"""Loopback Host/Origin and CSRF checks for local Web mutations.

The CSRF token is generated per server process and reaches the same-origin
frontend through ``GET /api/v1/csrf-bootstrap``. It is never embedded into
the served HTML, never logged, and no CORS headers are ever emitted, so a
cross-origin page cannot read the bootstrap response. Origin validation
parses the header as a URL and compares the hostname exactly — a prefix
match would accept ``http://localhost.evil.example``.
"""

from __future__ import annotations

import hmac
from urllib.parse import urlparse

from worktree_review.platform.web.errors import ApiError

_ALLOWED_HOSTNAMES = frozenset({"127.0.0.1", "localhost", "::1"})
_ALLOWED_ORIGIN_SCHEMES = frozenset({"http", "https"})


def _hostname(host: str | None) -> str:
    value = (host or "").strip()
    if value.startswith("["):
        # RFC 3986 bracketed IPv6 literal, e.g. "[::1]:8080".
        closing = value.find("]")
        return value[1:closing] if closing > 0 else value
    return value.split(":", 1)[0]


def is_loopback_host(host: str | None) -> bool:
    return _hostname(host) in _ALLOWED_HOSTNAMES


def is_loopback_origin(origin: str | None) -> bool:
    if not origin:
        # Non-browser clients (curl, scripts) send no Origin; the CSRF token
        # remains the real mutation guard.
        return True
    parsed = urlparse(origin)
    if parsed.scheme not in _ALLOWED_ORIGIN_SCHEMES:
        return False
    hostname = parsed.hostname
    if hostname is None:
        return False
    return hostname.lower() in _ALLOWED_HOSTNAMES


def assert_local_mutation_headers(
    host: str | None,
    origin: str | None,
    csrf_token: str | None,
    *,
    expected_csrf_token: str,
) -> None:
    if not is_loopback_host(host):
        raise ApiError(403, "forbidden_host", "mutations are only accepted from loopback")
    if not is_loopback_origin(origin):
        raise ApiError(403, "forbidden_origin", "Origin is not a loopback URL")
    if not csrf_token:
        raise ApiError(403, "missing_csrf_token", "X-CSRF-Token is required for mutations")
    if not hmac.compare_digest(csrf_token, expected_csrf_token):
        raise ApiError(403, "invalid_csrf_token", "X-CSRF-Token does not match this server")
