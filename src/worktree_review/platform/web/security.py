"""Loopback Host/Origin and CSRF checks for local Web mutations."""

from __future__ import annotations

from worktree_review.platform.web.errors import ApiError

_ALLOWED_HOSTS = {"127.0.0.1", "localhost"}


def _hostname(host: str | None) -> str:
    return (host or "").split(":", 1)[0]


def is_loopback_host(host: str | None) -> bool:
    return _hostname(host) in _ALLOWED_HOSTS


def is_loopback_origin(origin: str | None) -> bool:
    if not origin:
        return True
    return origin.startswith("http://127.0.0.1") or origin.startswith("http://localhost")


def assert_local_mutation_headers(
    host: str | None,
    origin: str | None,
    csrf_token: str | None,
) -> None:
    if not is_loopback_host(host):
        raise ApiError(403, "forbidden_host", "mutations are only accepted from loopback")
    if not is_loopback_origin(origin):
        raise ApiError(403, "forbidden_origin", "Origin is not a loopback URL")
    if not csrf_token:
        raise ApiError(403, "missing_csrf_token", "X-CSRF-Token is required for mutations")
