"""Shared utilities for the scraper package."""

import html
import ipaddress
import socket
from urllib.parse import urlparse


def is_safe_url(url: str) -> bool:
    """Block SSRF: dangerous schemes, private/internal IPs, localhost."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    hostname = parsed.hostname
    if not hostname:
        return False
    if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return False
    try:
        ip = ipaddress.ip_address(socket.gethostbyname(hostname))
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False
    except (socket.gaierror, ValueError):
        pass
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
