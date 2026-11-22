package discovery

import (
	"context"
	"crypto/tls"
	"net"
	"net/http"
	"regexp"
	"strings"
	"time"
)

// probeTimeout bounds a single HTTP fetch during probing.
const probeTimeout = 10 * time.Second

// userAgent is a browser UA so bare requests look like a real visitor.
const userAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

var titleRe = regexp.MustCompile(`(?is)<title[^>]*>(.*?)</title>`)

// HTTPFetcher is the cheapest transport tier: a plain GET with a browser UA.
// Python's curl tier is folded in here — a second GET with a slightly longer
// timeout and a different UA — rather than shelling out to the curl binary.
type HTTPFetcher struct {
	tiers []httpTier
}

type httpTier struct {
	client    *http.Client
	userAgent string
}

// NewHTTPFetcher builds the two-tier HTTP fetcher (requests, curl-equivalent).
func NewHTTPFetcher() *HTTPFetcher {
	// TLS config skips verification so universities with private/self-signed
	// certs (kuet, mist, bsmmu, etc.) are reachable — matching curl -k and the
	// Python scraper's behavior. We scrape public conference pages, so cert
	// trust is not a security concern here.
	tlsConfig := &tls.Config{InsecureSkipVerify: true}
	transport := &http.Transport{TLSClientConfig: tlsConfig}
	http1 := &http.Client{Timeout: probeTimeout, Transport: transport}
	http2 := &http.Client{Timeout: 15 * time.Second, Transport: transport}
	return &HTTPFetcher{tiers: []httpTier{
		{client: http1, userAgent: userAgent},
		{client: http2, userAgent: userAgent + " (probe)"},
	}}
}

// fetchBody runs each HTTP tier in turn and returns the first non-empty body.
func (f *HTTPFetcher) fetchBody(ctx context.Context, url string) (string, error) {
	var lastErr error
	for _, t := range f.tiers {
		body, err := t.get(ctx, url)
		if err != nil {
			lastErr = err
			continue
		}
		if body != "" {
			return body, nil
		}
	}
	if lastErr == nil {
		return "", nil
	}
	return "", lastErr
}

func (t httpTier) get(ctx context.Context, url string) (string, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return "", err
	}
	req.Header.Set("User-Agent", t.userAgent)
	req.Header.Set("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
	resp, err := t.client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", nil
	}
	buf := make([]byte, 0, 4096)
	tmp := make([]byte, 4096)
	for {
		n, err := resp.Body.Read(tmp)
		if n > 0 {
			buf = append(buf, tmp[:n]...)
		}
		if err != nil {
			break
		}
	}
	body := strings.TrimSpace(string(buf))
	if len(body) <= 50 {
		return "", nil
	}
	return body, nil
}

// TieredProbe verifies-aware transport escalation plus year verification.
//
// Tries the cheap HTTP tiers (requests, curl-equivalent) first, then the
// headless-Chrome tier, and caches bodies per URL so a year re-check never
// re-spends a request. It escalates tiers while fetched bodies fail
// verification, not just on fetch failure (a 200 carrying a challenge shell is
// a miss, not a page).
type TieredProbe struct {
	http    *HTTPFetcher
	browser *BrowserFetcher
	verify  bool
	cache   map[string][]string
	// bodiesSeen counts fetched bodies; >0 distinguishes "unreachable" from
	// "reachable but wrong edition".
	bodiesSeen int
}

// NewTieredProbe builds a probe. verify=false skips year checks
// (conf_info_bd). A non-nil browser is appended as the final escalation tier.
func NewTieredProbe(h *HTTPFetcher, browser *BrowserFetcher, verify bool) *TieredProbe {
	if h == nil {
		h = NewHTTPFetcher()
	}
	return &TieredProbe{http: h, browser: browser, verify: verify, cache: map[string][]string{}}
}

// fetchAll runs every tier in order and returns the first non-empty body,
// caching it. Returns "" when no tier yields content.
func (p *TieredProbe) fetchAll(ctx context.Context, url string) string {
	if bodies, ok := p.cache[url]; ok && len(bodies) > 0 {
		return bodies[0]
	}
	if body, _ := p.http.fetchBody(ctx, url); body != "" {
		p.bodiesSeen++
		p.cache[url] = []string{body}
		return body
	}
	if p.browser != nil {
		if body, err := p.browser.fetch(ctx, url); err == nil && body != "" {
			p.bodiesSeen++
			p.cache[url] = []string{body}
			return body
		}
	}
	return ""
}

// raw returns the best body across tiers for a URL, cached.
func (p *TieredProbe) raw(ctx context.Context, url string) (string, error) {
	return p.fetchAll(ctx, url), nil
}

// Raw returns the best rendered body across all tiers for a URL (HTTP then
// Chrome), or "" when no tier yields content. Exported so the extraction path
// can reuse the same transport resilience as discovery.
func (p *TieredProbe) Raw(ctx context.Context, url string) string {
	return p.fetchAll(ctx, url)
}

// verified returns the first body verifying as year, escalating tiers.
func (p *TieredProbe) verified(ctx context.Context, url string, year, prev int) (string, error) {
	bodies := p.cache[url]
	for _, b := range bodies {
		if !p.verify || verifyYearIsCurrent(b, year, prev) {
			return b, nil
		}
	}
	body := p.fetchAll(ctx, url)
	if body != "" {
		p.bodiesSeen++
		if p.verify && !verifyYearIsCurrent(body, year, prev) {
			return "", nil
		}
		return body, nil
	}
	return "", nil
}

// verifyYearIsCurrent is stronger than a bare substring check.
//
// A stale page can mention next year's number once, incidentally (a footer
// copyright range, an offhand deadline note). A page genuinely updated for
// that year features it far more prominently. Either signal suffices:
//  1. the year appears in <title> — a title reliably reflects the edition;
//  2. the year outnumbers the previous known year's mentions in the body.
func verifyYearIsCurrent(content string, targetYear, previousYear int) bool {
	if content == "" {
		return false
	}
	titleMatch := titleRe.FindStringSubmatch(content)
	if titleMatch != nil && strings.Contains(titleMatch[1], itoa(targetYear)) {
		return true
	}
	targetStr := itoa(targetYear)
	targetCount := strings.Count(content, targetStr)
	if targetCount == 0 {
		return false
	}
	if previousYear == 0 {
		return true
	}
	return targetCount >= strings.Count(content, itoa(previousYear))
}

// resolves reports whether a hostname has a DNS record — cheaper than an HTTP
// probe. Used to skip subdomain probes that don't exist. It is a var (not a
// func) so tests can stub DNS resolution.
var resolves = func(url string) bool {
	host := hostname(url)
	if host == "" {
		return false
	}
	ips, err := net.LookupIP(host)
	if err != nil {
		return false
	}
	return len(ips) > 0
}

// hostname extracts the host from a URL without importing net/url per-call.
func hostname(url string) string {
	s := strings.TrimPrefix(strings.TrimPrefix(url, "https://"), "http://")
	s = strings.SplitN(s, "/", 2)[0]
	s = strings.SplitN(s, "?", 2)[0]
	s = strings.SplitN(s, "#", 2)[0]
	if i := strings.LastIndex(s, "@"); i >= 0 {
		s = s[i+1:]
	}
	if i := strings.Index(s, ":"); i >= 0 {
		s = s[:i]
	}
	return s
}

// stripHTML removes tags, scripts and style blocks, collapsing whitespace.
func stripHTML(html string) string {
	for _, re := range []struct {
		name string
		expr *regexp.Regexp
	}{
		{"script", regexp.MustCompile(`(?is)<script\b[^>]*>.*?</script>`)},
		{"style", regexp.MustCompile(`(?is)<style\b[^>]*>.*?</style>`)},
		{"tag", regexp.MustCompile(`(?is)<[^>]+>`)},
	} {
		html = re.expr.ReplaceAllString(html, " ")
	}
	// Decode the few entities that appear in scraped university text.
	html = strings.ReplaceAll(html, "&nbsp;", " ")
	html = strings.ReplaceAll(html, "&amp;", "&")
	html = strings.ReplaceAll(html, "&quot;", "\"")
	html = strings.ReplaceAll(html, "&#39;", "'")
	html = strings.ReplaceAll(html, "&lt;", "<")
	html = strings.ReplaceAll(html, "&gt;", ">")
	return html
}
