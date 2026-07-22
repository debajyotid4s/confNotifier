package sources

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/url"
	"os"
	"path"
	"regexp"
	"strings"

	"github.com/PuerkitoBio/goquery"

	"github.com/anomalyco/bd-conf-bot/internal/browser"
	"github.com/anomalyco/bd-conf-bot/internal/db"
	"github.com/anomalyco/bd-conf-bot/internal/fetcher"
)

var (
	// Conference-link patterns (lowercase matching)
	confPatterns = []*regexp.Regexp{
		regexp.MustCompile(`ieee[a-z]+[\-_.]?\d{4}`),
		regexp.MustCompile(`ic[a-z]+[\-_.]?\d{4}`),
		regexp.MustCompile(`[a-z]+con\.\w+`),
		regexp.MustCompile(`[a-z]+icon\.\w+`),
		regexp.MustCompile(`conf[a-z]+[\-_.]?\d{4}`),
		regexp.MustCompile(`/(?:conf(?:erence)?|symposium|workshop|congress|summit|seminar|colloquium|convention|meeting|forum)[a-z]*[\-_.]?\d{4}`),
		regexp.MustCompile(`symposium`),
		regexp.MustCompile(`iccit`),
	}

	nonHTMLExtensions = map[string]struct{}{
		".pdf": {}, ".jpg": {}, ".jpeg": {}, ".png": {}, ".gif": {},
		".doc": {}, ".docx": {}, ".xls": {}, ".xlsx": {}, ".ppt": {}, ".pptx": {},
		".zip": {}, ".rar": {}, ".7z": {}, ".mp4": {}, ".mp3": {},
		".ico": {}, ".css": {}, ".js": {},
	}

	urlBlocklist = map[string]struct{}{
		"https://www.ieee.org":       {},
		"https://site.ieee.org":      {},
		"http://ieeeruetsb.net":      {},
	}
)

func isConferenceLink(href string) bool {
	if href == "" {
		return false
	}
	if _, blocked := urlBlocklist[href]; blocked {
		return false
	}
	if _, blocked := urlBlocklist[strings.TrimRight(href, "/")]; blocked {
		return false
	}

	parsed, err := url.Parse(href)
	if err != nil || parsed.Hostname() == "" {
		return false
	}

	// Skip non-HTML resources
	ext := strings.ToLower(path.Ext(parsed.Path))
	if _, ok := nonHTMLExtensions[ext]; ok {
		return false
	}

	lower := strings.ToLower(href)
	for _, pat := range confPatterns {
		if pat.MatchString(lower) {
			return true
		}
	}
	return false
}

func ScanHomepages(ctx context.Context, dbPool *db.Pool, domains []string, browserAgent *browser.Agent) ([]string, error) {
	var candidates []string

	for _, domain := range domains {
		url := fmt.Sprintf("https://www.%s", domain)
		result, err := fetcher.FetchHomepage(url)
		if err != nil {
			slog.Warn("failed to fetch homepage", "domain", domain, "error", err)
			continue
		}

		// Cache the successful strategy
		_ = dbPool.SaveDomainStrategy(ctx, domain, result.Strategy, result.URL)

		result.Doc.Find("a[href]").Each(func(i int, s *goquery.Selection) {
			href, exists := s.Attr("href")
			if !exists || href == "" || strings.HasPrefix(href, "#") || strings.HasPrefix(href, "javascript:") {
				return
			}
			fullURL := resolveURL(result.URL, href)
			if !isConferenceLink(fullURL) {
				return
			}
			seen, err := dbPool.IsLinkSeen(ctx, fullURL)
			if err != nil || seen {
				return
			}
			_ = dbPool.SaveSeenLink(ctx, fullURL, "homepage")
			candidates = append(candidates, fullURL)
		})
	}

	return candidates, nil
}

func LoadUniversities(path string) ([]string, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()

	body, err := io.ReadAll(f)
	if err != nil {
		return nil, err
	}

	var domains []string
	if err := json.Unmarshal(body, &domains); err != nil {
		return nil, err
	}
	return domains, nil
}

func resolveURL(base, href string) string {
	baseURL, err := url.Parse(base)
	if err != nil {
		return href
	}
	ref, err := url.Parse(href)
	if err != nil {
		return href
	}
	return baseURL.ResolveReference(ref).String()
}
