import logging
import subprocess
import time

from scraper.utils import is_safe_url

from .constants import CURL_TIMEOUT, RETRY_SLEEP, USER_AGENT

logger = logging.getLogger(__name__)


def _fetch_curl(url: str, timeout: int = CURL_TIMEOUT) -> str | None:
    """Fetch via the curl binary, retried once.

    Needed for hosts that emit HTTP headers urllib3 refuses to parse (buet.ac.bd,
    sust.edu). `-k` is deliberate: several .ac.bd hosts serve expired or
    mismatched certificates, and `is_safe_url` has already confirmed the target
    resolves to a public address, so the exposure is limited to reading a public
    page we would otherwise be unable to read at all.
    """
    if not is_safe_url(url):
        logger.warning("SSRF blocked (curl): %s", url)
        return None
    for attempt in range(2):
        try:
            proc = subprocess.run(
                ["curl", "-sS", "-L", "--max-time", str(timeout),
                 "--user-agent", USER_AGENT,
                 "-H", "Accept: text/html,application/xhtml+xml,*/*",
                 "-k", url],
                capture_output=True, timeout=timeout + 5,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.decode("utf-8", errors="replace")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        if attempt == 0:
            time.sleep(RETRY_SLEEP)
    return None
