package extract

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"confnotifier/internal/conf"
)

// HTTPExtractor is the production Extractor: it fetches a URL's text with a
// plain GET (the browser/fetch tiers are a later stage) and runs it through
// the LLM. It shares the client's rate limiter so DailyExhausted reflects the
// true budget.
type HTTPExtractor struct {
	client *Client
	http   *http.Client
}

// NewHTTPExtractor builds an extractor bound to the given LLM client.
func NewHTTPExtractor(client *Client) *HTTPExtractor {
	if client == nil {
		client = NewClient(ClientConfig{})
	}
	return &HTTPExtractor{
		client: client,
		http:   &http.Client{Timeout: 30 * time.Second},
	}
}

// Extract fetches a URL and returns its plain text. This is a minimal body
// extraction; the Playwright-based JS-render tier is added in a later stage.
func (e *HTTPExtractor) Extract(ctx context.Context, url string) (string, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return "", err
	}
	req.Header.Set("User-Agent", "confNotifier-scraper/1.0 (+https://github.com/confnotifier)")
	resp, err := e.http.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("fetch %s: HTTP %d", url, resp.StatusCode)
	}
	data, _ := io.ReadAll(io.LimitReader(resp.Body, 5<<20))
	return stripHTML(string(data)), nil
}

// ExtractConferences runs the LLM over page text.
func (e *HTTPExtractor) ExtractConferences(ctx context.Context, pageText, sourceURL string, previousDeadlines map[string]any, now time.Time, client *Client) (ExtractResult, error) {
	return ExtractConferences(pageText, sourceURL, previousDeadlines, now, client)
}

// DailyExhausted reflects the shared client's daily budget.
func (e *HTTPExtractor) DailyExhausted() bool {
	return e.client.DailyExhausted()
}

// stripHTML removes tags and decodes common entities — enough to feed the model
// prose; a proper HTML→text transform is a later stage.
func stripHTML(html string) string {
	var b strings.Builder
	inTag := false
	for _, r := range html {
		switch {
		case r == '<':
			inTag = true
		case r == '>':
			inTag = false
			b.WriteByte(' ')
		case !inTag:
			switch r {
			case '&':
				b.WriteString("&amp;")
			case '<':
				b.WriteString("&lt;")
			case '>':
				b.WriteString("&gt;")
			default:
				b.WriteRune(r)
			}
		}
	}
	return conf.FocusText(strings.Join(strings.Fields(b.String()), " "), 14000, 0)
}
