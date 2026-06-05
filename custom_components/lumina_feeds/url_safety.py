"""Safety helpers for user-supplied URLs.

Lumina Feeds lets users paste arbitrary RSS feed URLs in the config flow.
Without guards a user could be tricked into pasting (or accidentally enter)
a URL that points at Home Assistant's own internal network — the cloud-metadata
service at 169.254.169.254, a router admin page at 192.168.x, the HA API on
localhost, etc. The integration would then dutifully fetch that URL with HA's
network identity (classic SSRF).

This module provides two layers:

1. `is_safe_url(url)` — synchronous string + literal-IP check, suitable for
   validating in the config flow before persisting.
2. `resolve_is_safe(hass, host)` — DNS-resolves the host and checks every
   returned address is non-private. Runs in the executor (blocking call).
   Called at fetch time as defense-in-depth, since DNS records can change
   between config and fetch.
"""

from __future__ import annotations

import ipaddress
from socket import gaierror, gethostbyname_ex
from urllib.parse import urlparse


# Hostnames we always reject regardless of DNS resolution.
_BAD_HOSTNAMES = {"localhost", "ip6-localhost", "ip6-loopback"}

# Suffixes that strongly imply an internal/private network.
# Defense-in-depth on top of the IP-address check below.
_BAD_SUFFIXES = (".local", ".internal", ".lan", ".home", ".intranet", ".localhost")


def _ip_is_private(ip: ipaddress._BaseAddress) -> bool:
    """True if the IP belongs to any range we don't want to reach."""
    return (
        ip.is_private          # RFC1918 + ULA: 10/8, 172.16/12, 192.168/16, fc00::/7
        or ip.is_loopback      # 127.0.0.0/8, ::1
        or ip.is_link_local    # 169.254.0.0/16 (AWS metadata), fe80::/10
        or ip.is_multicast     # 224.0.0.0/4
        or ip.is_reserved
        or ip.is_unspecified   # 0.0.0.0, ::
    )


def is_safe_url(url: str) -> tuple[bool, str]:
    """Return (ok, reason). reason is a short slug suitable for translation keys."""
    if not isinstance(url, str) or not url.strip():
        return False, "empty"

    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        return False, "scheme"

    host = (parsed.hostname or "").lower()
    if not host:
        return False, "no_host"
    if host in _BAD_HOSTNAMES:
        return False, "private_host"
    if any(host.endswith(s) for s in _BAD_SUFFIXES):
        return False, "private_host"

    # If host is a literal IP, check directly. DNS-name hosts get resolved at
    # fetch time via resolve_is_safe().
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True, ""

    if _ip_is_private(ip):
        return False, "private_ip"
    return True, ""


async def resolve_is_safe(hass, host: str) -> tuple[bool, str]:
    """DNS-resolve host and confirm every returned IP is non-private.

    Returns (ok, reason). Run from an executor — gethostbyname_ex blocks.
    """
    if not host:
        return False, "no_host"

    # Literal IPs don't need resolution; is_safe_url already handled them.
    try:
        ip = ipaddress.ip_address(host)
        return (False, "private_ip") if _ip_is_private(ip) else (True, "")
    except ValueError:
        pass

    try:
        _, _, ips = await hass.async_add_executor_job(gethostbyname_ex, host)
    except (gaierror, UnicodeError):
        return False, "dns"

    for ip_str in ips:
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False, "bad_dns"
        if _ip_is_private(ip):
            return False, "private_ip"
    return True, ""
