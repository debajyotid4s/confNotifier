package discovery

import (
	"context"
	"log"
	"sort"
	"strings"

	"confnotifier/internal/store"
)

// Discoverer runs one discovery pass and returns new candidate URLs.
type Discoverer struct {
	pool    *store.Pool
	log     *log.Logger
	browser *BrowserFetcher
	crt     *Client
}

// New builds a Discoverer. A headless-Chrome fetcher is created up front and
// shared by every tier-3 lookup; it degrades to nil-safe no-ops when no
// browser binary is installed. The crt.sh client is created up front too; it
// degrades to a no-op when it cannot reach the cert-transparency log.
func New(p *store.Pool, logger *log.Logger) *Discoverer {
	if logger == nil {
		logger = log.Default()
	}
	return &Discoverer{
		pool:    p,
		log:     logger,
		browser: NewBrowserFetcher(""),
		crt:     NewClient(defaultQueries),
	}
}

// WithCrtClient overrides the crt.sh discovery client (used by tests to point
// at a mock cert-transparency log).
func (d *Discoverer) WithCrtClient(c *Client) *Discoverer {
	d.crt = c
	return d
}

// Run discovers candidates from homepage scanning and special sources, merges
// pending/retryable URLs from previous runs, and persists new claims.
//
// It returns the deduplicated candidate list and the retryable URLs. Each
// discovery source degrades independently: a failed runner logs and continues,
// never aborting the run.
func (d *Discoverer) Run(ctx context.Context) ([]string, []string) {
	sources := LoadSources("")
	regular := RegularDomains(sources)
	special := []Source{}
	for _, s := range sources {
		if s.Type == "regular" || s.Type == "" {
			continue
		}
		special = append(special, s)
	}

	var candidates []string

	// Homepage scanning: every regular homepage, anchored through classify_link.
	if len(regular) > 0 {
		fetch := NewHTTPFetcher()
		newCands, known := d.runHomepage(ctx, fetch, regular)
		candidates = append(candidates, newCands...)
		_ = known
	}

	// Special sources: path_probe / subdomain_probe / conf_info_bd.
	if len(special) > 0 {
		newCands, newRows := d.runSpecial(ctx, special)
		candidates = append(candidates, newCands...)
		if len(newRows) > 0 {
			if _, err := store.SaveSeenLinksBulk(ctx, d.pool, toSeenLinks(newRows)); err != nil {
				d.log.Printf("discovery: persist special claims: %v", err)
			}
		}
	}

	// Certificate-transparency sweep: queue any .ac.bd / .edu.bd host we have
	// never seen (often a fresh conference subdomain) as a pending candidate.
	// This is the one net that catches a subdomain link-discovery has never
	// observed, so it runs independent of the others and fails open.
	if d.crt != nil {
		if n, err := Discover(ctx, d.pool, d.crt); err != nil {
			d.log.Printf("discovery: crt.sh sweep: %v", err)
		} else if n > 0 {
			d.log.Printf("discovery: crt.sh queued %d new candidate(s)", n)
		}
	}

	// Merge pending + retryable URLs from earlier runs.
	pending, err := store.LoadPendingURLs(ctx, d.pool)
	if err != nil {
		d.log.Printf("discovery: load pending: %v", err)
	}
	retryable, err := store.LoadRetryableURLs(ctx, d.pool)
	if err != nil {
		d.log.Printf("discovery: load retryable: %v", err)
	}
	retryURLs := make([]string, 0, len(retryable))
	for _, sl := range retryable {
		retryURLs = append(retryURLs, sl.URL)
	}

	all := append(candidates, pending...)
	unique := dedupSort(all)
	return unique, retryURLs
}

// runHomepage scans each regular homepage and returns new candidates plus the
// set of URLs already known (for dedup against special sources).
func (d *Discoverer) runHomepage(ctx context.Context, fetch *HTTPFetcher, domains []string) ([]string, map[string]struct{}) {
	known := map[string]struct{}{}
	var out []string
	for _, base := range domains {
		anchors := ScanHomepage(ctx, fetch, base)
		for _, a := range anchors {
			out = append(out, a.URL)
			known[canonical(a.URL)] = struct{}{}
		}
	}
	return out, known
}

// runSpecial runs every special source with learned state, persists new claims,
// and returns them plus their (url, source) rows.
func (d *Discoverer) runSpecial(ctx context.Context, sources []Source) ([]string, [][2]string) {
	stateStore := NewStateStore(d.pool)
	states := stateStore.LoadAll(ctx)
	snap := snapshot(states)

	var allCands []string
	var allRows [][2]string
	seen := map[string]struct{}{}

	for _, s := range specialSources(sources) {
		name := sourceKey(s)
		state := states[name]
		if state == nil {
			state = &SourceState{Name: name}
		}
		disc := NewDiscovery(nil)
		probe := NewTieredProbe(NewHTTPFetcher(), d.browser, s.VerifyYear)
		var confirmed bool
		switch s.Type {
		case "path_probe":
			confirmed, _ = handlePathProbe(ctx, s, disc, state, probe)
		case "subdomain_probe":
			confirmed = handleSubdomainProbe(ctx, s, disc, state, probe)
		case "conf_info_bd":
			confirmed = handleConfInfoBD(ctx, s, disc, probe)
		default:
			continue
		}

		// Seed likely-CFP subdomains for prioritised universities so future
		// editions on those hostnames are probed before link-discovery sees
		// them. Idempotent and applied every run.
		if s.Type == "subdomain_probe" {
			seedSubdomainPrefixes(&s)
		}

		if confirmed {
			state.ConsecutiveFail = 0
		} else {
			state.ConsecutiveFail++
		}

		if disc.Len() > 0 {
			allCands = append(allCands, disc.candidates...)
			allRows = append(allRows, disc.rows...)
			for _, c := range disc.candidates {
				seen[canonical(c)] = struct{}{}
			}
		}
		states[name] = state
	}

	changed := changedStates(states, snap)
	if _, err := stateStore.SaveAll(ctx, changed); err != nil {
		d.log.Printf("discovery: save source state: %v", err)
	}
	return allCands, allRows
}

// specialSources filters to non-regular special sources.
func specialSources(sources []Source) []Source {
	out := []Source{}
	for _, s := range sources {
		if s.Type == "path_probe" || s.Type == "subdomain_probe" || s.Type == "conf_info_bd" {
			out = append(out, s)
		}
	}
	return out
}

// sourceKey returns the stable per-source key.
func sourceKey(s Source) string {
	if s.Name != "" {
		return s.Name
	}
	if s.BaseURL != "" {
		return s.BaseURL
	}
	if s.BaseDomain != "" {
		return s.BaseDomain
	}
	return s.Type
}

// dedupSort returns a sorted, de-duplicated, canonical URL list.
func dedupSort(in []string) []string {
	seen := map[string]struct{}{}
	out := []string{}
	for _, u := range in {
		c := canonical(u)
		if _, ok := seen[c]; ok {
			continue
		}
		seen[c] = struct{}{}
		out = append(out, u)
	}
	sort.Strings(out)
	return out
}

// canonical folds a URL to a dedup key (scheme/host/path, no www, no trailing
// slash, no tracking params).
func canonical(u string) string {
	lower := strings.ToLower(strings.TrimSpace(u))
	lower = strings.TrimPrefix(lower, "http://")
	lower = strings.TrimPrefix(lower, "https://")
	// drop query string and fragment
	if i := strings.Index(lower, "?"); i >= 0 {
		lower = lower[:i]
	}
	if i := strings.Index(lower, "#"); i >= 0 {
		lower = lower[:i]
	}
	parts := strings.SplitN(lower, "/", 2)
	host := strings.TrimPrefix(parts[0], "www.")
	path := ""
	if len(parts) == 2 {
		path = "/" + parts[1]
	}
	path = strings.TrimRight(path, "/")
	return "https://" + host + path
}

func toSeenLinks(rows [][2]string) []store.SeenLink {
	out := make([]store.SeenLink, 0, len(rows))
	for _, r := range rows {
		out = append(out, store.SeenLink{URL: r[0], Source: "special", Status: "pending"})
	}
	return out
}
