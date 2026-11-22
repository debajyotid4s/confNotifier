package discovery

import (
	"context"
	"regexp"
	"strings"
	"time"

	"confnotifier/internal/conf"
)

// anchorRe matches <a ... href="..."> and captures the href value.
func anchorRe() *regexp.Regexp {
	return regexp.MustCompile(`(?is)<a\b[^>]*?\shref\s*=\s*["'](.*?)["']`)
}

// nowTime is the injectable clock (tests override via SetDiscoveryNow).
var nowTime = defaultNow

func defaultNow() time.Time { return time.Now().UTC() }

// classifyConferenceLink is the discovery-side wrapper around the shared
// classifier. It answers the same question as scraper/patterns/classify.py:
// does this URL look like a conference/CFP page?
func classifyConferenceLink(url string) (bool, string) {
	return conf.ClassifyLink(url, nowTime())
}

// Anchor is one discovered candidate link and the reason it passed the filter.
type Anchor struct {
	URL    string
	Reason string
}

// ScanHomepage fetches a homepage and returns anchors that classify as
// conference/CFP links. Mirrors scraper/sources/homepage_links/links.py
// + runner.py: every <a href> is run through classify_link, and only positives
// are returned (negative signals reject the rest).
func ScanHomepage(ctx context.Context, fetch *HTTPFetcher, homepage string) []Anchor {
	body, err := fetch.fetchBody(ctx, homepage)
	if err != nil || body == "" {
		return nil
	}
	anchors := extractAnchors(body, homepage)
	out := make([]Anchor, 0, len(anchors))
	for _, h := range anchors {
		if accepted, reason := classifyConferenceLink(h); accepted {
			out = append(out, Anchor{URL: h, Reason: reason})
		}
	}
	return out
}

// linkRe matches <a ... href="..."> and captures the href.
var linkRe = anchorRe()

// extractAnchors pulls absolute URLs from every href.
func extractAnchors(html, base string) []string {
	hrefs := linkRe.FindAllStringSubmatch(html, -1)
	out := make([]string, 0, len(hrefs))
	for _, m := range hrefs {
		if len(m) < 2 {
			continue
		}
		href := strings.TrimSpace(m[1])
		if href == "" || strings.HasPrefix(href, "#") ||
			strings.HasPrefix(href, "javascript:") ||
			strings.HasPrefix(href, "mailto:") ||
			strings.HasPrefix(href, "tel:") {
			continue
		}
		out = append(out, absURL(base, href))
	}
	return out
}

// absURL resolves a relative href against the base URL.
func absURL(base, href string) string {
	if strings.HasPrefix(href, "http://") || strings.HasPrefix(href, "https://") {
		return href
	}
	if strings.HasPrefix(href, "//") {
		return "https:" + href
	}
	base = strings.TrimSuffix(base, "/")
	if strings.HasPrefix(href, "/") {
		return base + href
	}
	return base + "/" + href
}
