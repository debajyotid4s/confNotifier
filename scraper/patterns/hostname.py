"""Certificate-transparency hostname filter."""

import re

from .blocklists import INFRA_LABELS
from .host import _host_labels
from .positive import _LOOKALIKE_WORDS
from .signals import _positive_signal
from .url import is_blocked_host
from .year import _year_verdict


def is_conference_hostname(name: str, now=None) -> bool:
    """Certificate-transparency filter: does this DNS name look like a CFP site?

    Stricter than classify_link because we only have a hostname to go on.
    """
    host = (name or "").lower().strip().lstrip("*.").strip(".")
    if not host or is_blocked_host(host):
        return False
    labels = _host_labels(host)
    if not labels:
        return False
    if labels[0] in INFRA_LABELS:
        return False
    # Strip a trailing year to compare the bare label against infra names
    # (e.g. "portal2027" is still a portal).
    bare = re.sub(r"[-_.]?(?:19|20)\d{2}$", "", labels[0])
    if bare in INFRA_LABELS or bare in _LOOKALIKE_WORDS:
        return False
    if _year_verdict(host, now) == "stale":
        return False
    return _positive_signal(labels, "") is not None
