// Package discovery finds new conference candidate URLs from external
// sources. crt.sh monitors certificate-transparency logs for new TLS
// certificates issued to .ac.bd / .edu.bd domains, which is a strong signal
// that a Bangladeshi university is running a website (often hosting a CFP).
//
// This replaces the retired Python certspotter/crt.sh code with a cleaner,
// single-purpose implementation.
package discovery

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"

	"confnotifier/internal/store"
)

// crtShQueryURL is the crt.sh certificate-transparency endpoint.
const crtShQueryURL = "https://crt.sh/"

// defaultQueries are the base patterns watched for conference sites.
//
// crt.sh's JSON API rejects the '%' wildcard (it only honours it in the
// JavaScript search UI), so we query the bare TLD labels "ac.bd" / "edu.bd"
// instead. crt.sh treats a bare label as a broad match and returns every cert
// whose subject contains it — effectively a wildcard over the whole TLD.
var defaultQueries = []string{"ac.bd", "edu.bd"}

// Client fetches crt.sh results.
type Client struct {
	http    *http.Client
	queries []string
}

// NewClient builds a crt.sh discovery client.
func NewClient(queries []string) *Client {
	if len(queries) == 0 {
		queries = defaultQueries
	}
	return &Client{
		http:    &http.Client{Timeout: 60 * time.Second},
		queries: queries,
	}
}

// crtRow is one certificate-transparency log entry.
type crtRow struct {
	CommonName string          `json:"common_name"`
	NameValues json.RawMessage `json:"name_value"`
}

// nameValues parses the name_value field, which may be a JSON array of strings
// or a single string.
func (r crtRow) nameValues() []string {
	var arr []string
	if len(r.NameValues) > 0 && r.NameValues[0] == '[' {
		_ = json.Unmarshal(r.NameValues, &arr)
	} else if len(r.NameValues) > 0 {
		var s string
		if err := json.Unmarshal(r.NameValues, &s); err == nil {
			arr = []string{s}
		}
	}
	return arr
}

// FetchCertificates returns all subject names from crt.sh for the watched
// patterns. crt.sh is rate-limited and slow, so we poll one query at a time.
func (c *Client) FetchCertificates(ctx context.Context) ([]string, error) {
	seen := map[string]bool{}
	var names []string
	for _, q := range c.queries {
		raw, err := c.fetchCrtSh(ctx, q)
		if err != nil {
			// crt.sh is flaky; log and continue rather than failing the run.
			return names, fmt.Errorf("crt.sh query %q: %w", q, err)
		}
		var rows []crtRow
		if err := json.Unmarshal(raw, &rows); err != nil {
			return names, fmt.Errorf("parse crt.sh %q: %w", q, err)
		}
		for _, row := range rows {
			for _, name := range row.nameValues() {
				name = strings.TrimSpace(name)
				if name == "" {
					continue
				}
				domain := normalizeCertName(name)
				if domain == "" || seen[domain] {
					continue
				}
				seen[domain] = true
				names = append(names, domain)
			}
		}
	}
	return names, nil
}

func (c *Client) fetchCrtSh(ctx context.Context, query string) ([]byte, error) {
	// crt.sh's JSON API rejects the '%' wildcard and treats "LIKE <label>" as
	// an exact match (returning nothing for a bare label), so we pass the TLD
	// label as-is. A bare label matches every cert whose subject contains it,
	// which is the wildcard behaviour we want.
	u := crtShQueryURL + "?q=" + url.QueryEscape(query) + "&output=json"
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", "confNotifier-discovery/1.0")
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("crt.sh HTTP %d (url=%s)", resp.StatusCode, u)
	}
	return io.ReadAll(io.LimitReader(resp.Body, 20<<20))
}

// normalizeCertName cleans a cert subject name for queueing.
// crt.sh returns names like "foo.bar.ac.bd" or "*.ac.bd"; we keep the full
// hostname (minus any wildcard prefix) so CFP subdomains are discoverable.
func normalizeCertName(name string) string {
	name = strings.ToLower(strings.TrimPrefix(name, "*."))
	name = strings.TrimSuffix(name, ".")
	name = strings.TrimSpace(name)
	if name == "" || strings.Contains(name, "\\") {
		return ""
	}
	return name
}

// Discover runs one discovery pass: fetch certs, filter to conference-worthy
// domains, and queue them as pending seen_links. When dryRun is true the sweep
// still runs and returns the count of new candidates, but persists nothing —
// keeping a scrape dry run fully read-only.
func Discover(ctx context.Context, p *store.Pool, client *Client, dryRun bool) (int, error) {
	names, err := client.FetchCertificates(ctx)
	if err != nil {
		return 0, err
	}
	var candidates []string
	for _, name := range names {
		if isConferenceDomain(name) {
			candidates = append(candidates, "https://"+name)
		}
	}
	if len(candidates) == 0 {
		return 0, nil
	}
	if !dryRun {
		rows := make([]store.SeenLink, 0, len(candidates))
		for _, c := range candidates {
			rows = append(rows, store.SeenLink{URL: c, Source: "crt.sh", Status: "pending"})
		}
		if _, err := store.SaveSeenLinksBulk(ctx, p, rows); err != nil {
			return 0, fmt.Errorf("queue crt.sh candidates: %w", err)
		}
	}
	return len(candidates), nil
}

// isConferenceDomain filters cert names to those likely to host a conference.
func isConferenceDomain(name string) bool {
	lower := strings.ToLower(name)
	// Only watch the Bangladesh academic TLDs.
	if !strings.HasSuffix(lower, ".ac.bd") && !strings.HasSuffix(lower, ".edu.bd") {
		return false
	}
	// Skip obvious non-conference infra.
	for _, bad := range []string{"mail.", "smtp.", "mx.", "dns.", "ns1.", "ns2.", "vpn.", "vpn1.", "vpn2."} {
		if strings.HasPrefix(lower, bad) {
			return false
		}
	}
	return true
}
