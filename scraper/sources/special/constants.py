USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

PROBE_TIMEOUT = 10
#: Minimum body size for a probe to count as a real page.
MIN_CONTENT = 500
#: Lower bar for the curl tier: small SPA shells are worth verifying, and the
#: year check (not size) is what accepts or rejects them.
CURL_MIN_CONTENT = 200
