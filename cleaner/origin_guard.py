"""Reject changing requests that come from a web page on another site.

Any web page you have open can make your browser send a POST to
http://127.0.0.1:<port>. Browsers attach an Origin header to those requests, so
the server checks it. A request with no Origin header (curl, scripts, tests) is
not a browser request and passes.

An Origin is allowed when it is a loopback address on any port, or is listed in
ALLOWED_ORIGINS (comma separated, for example a LAN or Tailscale address).
"""

from __future__ import annotations

from urllib.parse import urlsplit

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _normalize(origin: str) -> str:
    return origin.strip().rstrip("/").lower()


def parse_origin_list(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(dict.fromkeys(_normalize(part) for part in raw.split(",") if part.strip()))


def origin_allowed(origin: str, extra_origins: tuple[str, ...] = (), *, allow_loopback: bool = True) -> bool:
    value = _normalize(origin)
    if value in {_normalize(item) for item in extra_origins}:
        return True
    if not allow_loopback:
        return False
    try:
        parts = urlsplit(value)
        hostname = parts.hostname
    except ValueError:
        return False
    if parts.scheme not in {"http", "https"}:
        return False
    if parts.username or parts.password or parts.path or parts.query or parts.fragment:
        return False
    return hostname in LOOPBACK_HOSTS


def request_allowed(
    method: str,
    origin: str | None,
    sec_fetch_site: str | None,
    extra_origins: tuple[str, ...] = (),
    *,
    allow_loopback: bool = True,
) -> tuple[bool, str]:
    """Return (allowed, reason). Only changing methods are checked."""
    if method.upper() not in UNSAFE_METHODS:
        return True, ""
    if origin is None:
        if (sec_fetch_site or "").lower() == "cross-site":
            return False, "Cross-site requests are not allowed"
        return True, ""
    if origin_allowed(origin, extra_origins, allow_loopback=allow_loopback):
        return True, ""
    return False, f"Origin not allowed: {origin[:200]}"
