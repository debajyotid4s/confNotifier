"""Hostname label helpers."""

import re

from .positive import _HOST_LABEL_SHAPES, _LOOKALIKE_WORDS


def _host_labels(hostname: str) -> list[str]:
    """Hostname labels with the public suffix and 'www' removed.

    "icerie2027.sust.edu" -> ["icerie2027", "sust"]
    """
    host = (hostname or "").lower().strip(".")
    if host.startswith("www."):
        host = host[4:]
    parts = [p for p in host.split(".") if p]
    # Drop common public-suffix tails so the university label is not treated
    # as a candidate acronym: ac.bd, edu.bd, org.bd, com, edu, org, net...
    tail = {"ac", "edu", "org", "com", "net", "gov", "info", "bd", "io", "co"}
    while len(parts) > 1 and parts[-1] in tail:
        parts.pop()
    return parts


def _label_looks_like_conference(label: str) -> bool:
    """True when a host label matches an acronym shape and is not a real word."""
    bare = re.sub(r"[-_.]?(?:19|20)\d{2}$", "", label)
    if bare in _LOOKALIKE_WORDS or label in _LOOKALIKE_WORDS:
        return False
    return any(shape.match(label) for shape in _HOST_LABEL_SHAPES)
