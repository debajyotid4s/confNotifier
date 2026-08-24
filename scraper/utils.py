"""Shared utilities for the scraper package."""

import html
import ipaddress
import socket
from urllib.parse import urlparse


def is_safe_url(url: str) -> bool:
    """Block SSRF: dangerous schemes, private/internal IPs, localhost. Fail-closed on DNS failure, handles IPv4+IPv6."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    hostname = parsed.hostname
    if not hostname:
        return False
    if hostname.lower() in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return False
    # Direct IP literal
    try:
        ip = ipaddress.ip_address(hostname.strip("[]"))
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
        return True
    except ValueError:
        pass
    # DNS resolution — check all A/AAAA records, fail-closed on failure
    try:
        # Use getaddrinfo for IPv4+IPv6, with timeout via socket default
        old_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(3)
        try:
            infos = socket.getaddrinfo(hostname, None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
        finally:
            socket.setdefaulttimeout(old_timeout)
        if not infos:
            return False
        for _, _, _, _, sockaddr in infos:
            ip_str = sockaddr[0]
            try:
                ip = ipaddress.ip_address(ip_str)
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                    return False
            except ValueError:
                continue
    except (socket.gaierror, ValueError, OSError, UnicodeError):
        # Fail-closed: if we can't resolve, don't allow (prevents DNS rebinding bypass)
        return False
    return True


def escape_html(text) -> str:
    """Escape HTML special characters for Telegram HTML rendering (None-safe)."""
    if text is None:
        return ""
    return html.escape(str(text), quote=False)


def resolve_channel(value: str) -> str:
    """Resolve a channel reference to an @handle: accepts @handle, chat ID, or a
    t.me/... link (bare or with scheme)."""
    if "t.me/" in value:
        return "@" + value.split("t.me/")[-1].strip("/")
    return value
