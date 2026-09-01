import logging

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

FETCH_TIERS = ("requests", "curl", "playwright")
REQUEST_TIMEOUT = 10
CURL_TIMEOUT = 15
RETRY_SLEEP = 3

#: Cloudflare's interstitial, which returns HTTP 200 with no real content.
_CHALLENGE_MARKER = "Just a moment"

# Malformed headers from several .ac.bd hosts make urllib3 very noisy.
logging.getLogger("urllib3.connection").setLevel(logging.ERROR)
