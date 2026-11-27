// probe_extractor.go — an Extractor backed by the discovery TieredProbe.
//
// The plain HTTPExtractor does a single GET, which fails on the university
// sites the scraper exists to cover: private/self-signed certs (kuet, mist,
// bsmmu) and Cloudflare-protected pages. The TieredProbe escalates through
// insecure-TLS HTTP tiers and finally headless Chrome, so extraction uses it
// to reach the same pages discovery does.
//
// Lives in pipeline (not extract) to avoid an import cycle: extract imports
// pipeline for the Extractor interface, so the adapter must sit above extract.
package pipeline

import (
	"context"
	"strings"
	"time"

	"confnotifier/internal/discovery"
	"confnotifier/internal/extract"
)

// ProbeExtractor adapts the discovery TieredProbe to the Extractor interface.
type ProbeExtractor struct {
	probe *discovery.TieredProbe
}

// NewProbeExtractor builds an extractor that fetches via the tiered probe.
// A nil browser lets the probe degrade gracefully when Chrome is absent.
func NewProbeExtractor(browser *discovery.BrowserFetcher) *ProbeExtractor {
	if browser == nil {
		browser = discovery.NewBrowserFetcher("")
	}
	return &ProbeExtractor{probe: discovery.NewTieredProbe(discovery.NewHTTPFetcher(), browser, false)}
}

// Extract fetches a URL's rendered text through the tiered probe.
func (e *ProbeExtractor) Extract(ctx context.Context, url string) (string, error) {
	body := e.probe.Raw(ctx, url)
	if strings.TrimSpace(body) == "" {
		return "", context.DeadlineExceeded // surface as a retryable miss
	}
	return body, nil
}

// ExtractConferences runs the LLM over page text (shared with HTTPExtractor).
func (e *ProbeExtractor) ExtractConferences(ctx context.Context, pageText, sourceURL string, previousDeadlines map[string]any, now time.Time, client *extract.Client) (extract.ExtractResult, error) {
	return extract.ExtractConferences(pageText, sourceURL, previousDeadlines, now, client)
}

// DailyExhausted is always false for the probe path (no LLM budget there).
func (e *ProbeExtractor) DailyExhausted() bool { return false }
