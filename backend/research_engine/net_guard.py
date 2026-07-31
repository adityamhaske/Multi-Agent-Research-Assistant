"""
SSRF guard for agent-controlled URL fetches (docs/engineering/06_Security.md §3).

The URL passed to read_webpage is influenced by an LLM steered by untrusted web
content, so it is treated as hostile: scheme/port allowlist, resolve every
address and reject private/loopback/link-local ranges, and pin the connection to
a validated IP to defeat DNS rebinding.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

_ALLOWED_SCHEMES = {"http", "https"}
_ALLOWED_PORTS = {80, 443, 8080, 8443}


class SSRFBlocked(Exception):
    """Raised when a URL fails the SSRF policy."""


def _ip_is_forbidden(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
        # CGNAT 100.64.0.0/10
        or (addr.version == 4 and addr in ipaddress.ip_network("100.64.0.0/10"))
    )


def validate_url(url: str) -> list[str]:
    """
    Validate a URL against the SSRF policy.

    Returns the list of resolved IPs (safe to connect to). Raises SSRFBlocked
    with a reason otherwise. Call once per hop (redirects must re-validate).
    """
    if not url:
        raise SSRFBlocked("empty url")

    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise SSRFBlocked(f"scheme '{parsed.scheme}' not allowed")
    if parsed.username or parsed.password:
        raise SSRFBlocked("userinfo in URL not allowed")

    host = parsed.hostname
    if not host:
        raise SSRFBlocked("no host in URL")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port not in _ALLOWED_PORTS:
        raise SSRFBlocked(f"port {port} not allowed")

    # Reject literal IPs in forbidden ranges before any DNS.
    try:
        ipaddress.ip_address(host)
        if _ip_is_forbidden(host):
            raise SSRFBlocked(f"host IP {host} is in a forbidden range")
        return [host]
    except ValueError:
        pass  # not a literal IP — resolve it

    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise SSRFBlocked(f"DNS resolution failed: {e}") from e

    resolved = {info[4][0] for info in infos}
    if not resolved:
        raise SSRFBlocked("no addresses resolved")
    for ip in resolved:
        if _ip_is_forbidden(ip):
            raise SSRFBlocked(f"resolved IP {ip} is in a forbidden range")
    return sorted(resolved)
