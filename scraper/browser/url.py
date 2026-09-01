from urllib.parse import urlparse, urlunparse, quote, unquote


def _normalize_url(url: str) -> str:
    """Percent-encode special chars in URL path without double-encoding."""
    try:
        parsed = urlparse(url)
        path = quote(unquote(parsed.path), safe="/:@!$&'()*+,;=-._~%")
        query = quote(unquote(parsed.query), safe="&=")
        return urlunparse(
            (parsed.scheme, parsed.netloc, path, parsed.params, query, parsed.fragment)
        )
    except Exception:
        return url
