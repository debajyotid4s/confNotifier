USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

PROBE_TIMEOUT = 10
#: Minimum body size for a probe to count as a real page. Single-page apps ship
#: a small HTML shell, so path handlers lower this.
MIN_CONTENT = 500
MIN_CONTENT_SPA = 200
