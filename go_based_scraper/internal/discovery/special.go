package discovery

import (
	"context"
	"fmt"
	"strings"
)

// Discovery accumulates candidates for one run and dedups them against
// seen_links. Handlers claim URLs; the caller persists everything in one
// batch. Mirrors scraper/sources/special/discovery.py.
type Discovery struct {
	seen       map[string]struct{}
	candidates []string
	rows       [][2]string
}

// NewDiscovery builds a Discovery deduped against already-seen URLs.
func NewDiscovery(seen []string) *Discovery {
	m := make(map[string]struct{}, len(seen))
	for _, u := range seen {
		m[canonical(u)] = struct{}{}
	}
	return &Discovery{seen: m}
}

// isNew reports whether a URL (canonically) hasn't been claimed this run.
func (d *Discovery) isNew(url string) bool {
	_, ok := d.seen[canonical(url)]
	return !ok
}

// claim records a newly discovered URL, ignoring duplicates.
func (d *Discovery) claim(url string) {
	key := canonical(url)
	if _, ok := d.seen[key]; ok {
		return
	}
	d.seen[key] = struct{}{}
	d.candidates = append(d.candidates, url)
	d.rows = append(d.rows, [2]string{url, "special"})
}

// Len returns the number of new candidates claimed.
func (d *Discovery) Len() int { return len(d.candidates) }

// Rows returns the (url, source) pairs for bulk persistence.
func (d *Discovery) Rows() [][2]string { return d.rows }

// --- path_probe ---

func expandPath(base, pattern string, year int) string {
	if pattern == "" {
		return base
	}
	return base + replaceAll(pattern, "{year}", itoa(year))
}

// handlePathProbe is the path_probe handler. See the Python runner for the
// tiered, learned-pattern-first, state-self-advancing contract.
//
// Returns confirmed (a live edition was verified this run) and drift (a
// long-working pattern suddenly missed — possible URL restructuring).
func handlePathProbe(ctx context.Context, s Source, d *Discovery, state *SourceState, probe *TieredProbe) (confirmed, drift bool) {
	base := trimRight(s.BaseURL, "/")
	if base == "" {
		return false, false
	}
	years := probeYears(s, state.LastConfirmedYear, nowTime())
	if len(years) == 0 {
		return false, false
	}
	interval := cadenceStep(s)
	ordered := orderCandidates(s.Candidates, state.WorkingCandidate)
	primary := ""
	if len(ordered) > 0 {
		primary = ordered[0]
	}

	confirm := func(year int, pattern, url string) {
		if state.LastConfirmedYear == nil || year >= *state.LastConfirmedYear {
			state.LastConfirmedYear = &year
			if state.WorkingCandidate == "" {
				state.WorkingCandidate = pattern
			}
		}
		if d.isNew(url) {
			d.claim(url)
		}
	}

	// Tier 1 — learned (or first) pattern across all years, newest first.
	primaryHitNewest := false
	for _, year := range years {
		url := expandPath(base, primary, year)
		if _, err := probe.verified(ctx, url, year, year-interval); err == nil {
			confirmed = true
			confirm(year, primary, url)
			primaryHitNewest = (year == years[0])
			break
		}
	}

	// Tier 2 — remaining substantive patterns, unseen URLs only.
	substantive := []string{}
	for _, p := range ordered[1:] {
		if p != "" {
			substantive = append(substantive, p)
		}
	}
	confirmedYears := confirmedYearSet(state, years)
	for _, year := range years {
		if confirmedYears[year] {
			continue
		}
		for _, pattern := range substantive {
			url := expandPath(base, pattern, year)
			if !d.isNew(url) {
				continue
			}
			if _, err := probe.verified(ctx, url, year, year-interval); err == nil {
				confirmed = true
				confirm(year, pattern, url)
				confirmedYears[year] = true
				break
			}
		}
	}

	// Tier 3 — homepage discovery for unconfirmed years, newest first.
	rescued := false
	if s.DiscoverLinks {
		for _, year := range years {
			if confirmedYears[year] {
				continue
			}
			if hit := discoverYearLinks(ctx, probe, base, year, d, year-interval); hit != "" {
				rescued = true
				confirmed = true
				confirmedYears[year] = true
				if state.LastConfirmedYear == nil || year >= *state.LastConfirmedYear {
					state.LastConfirmedYear = &year
				}
				break
			}
		}
	}

	// Tier 2b — bare base fallback, runs last so it can never shadow discovery.
	if hasEmptyPattern(ordered) {
		for _, year := range years {
			if confirmedYears[year] {
				continue
			}
			if _, err := probe.verified(ctx, base, year, year-interval); err == nil {
				confirmed = true
				confirm(year, "", base)
				break
			}
		}
	}

	if rescued && primary != "" && !primaryHitNewest {
		drift = true
	}
	return confirmed, drift
}

// confirmedYearSet returns the set of years already confirmed for a source.
func confirmedYearSet(state *SourceState, years []int) map[int]bool {
	out := map[int]bool{}
	if state.LastConfirmedYear != nil {
		// Everything up to and including the confirmed year counts as known.
		for _, y := range years {
			if y <= *state.LastConfirmedYear {
				out[y] = true
			}
		}
	}
	return out
}

func hasEmptyPattern(candidates []string) bool {
	for _, c := range candidates {
		if c == "" {
			return true
		}
	}
	return false
}

// discoverYearLinks crawls the homepage for any link carrying the target year.
func discoverYearLinks(ctx context.Context, probe *TieredProbe, base string, year int, d *Discovery, prev int) string {
	base = trimRight(base, "/")
	if base == "" {
		return ""
	}
	body, err := probe.raw(ctx, base)
	if err != nil || body == "" {
		return ""
	}
	seen := 0
	for _, href := range extractAnchors(body, base) {
		if !strings.Contains(href, itoa(year)) {
			continue
		}
		if !d.isNew(href) {
			continue
		}
		if seen >= 10 {
			break
		}
		seen++
		if b, err := probe.raw(ctx, href); err == nil && b != "" &&
			verifyYearIsCurrent(b, year, prev) {
			d.claim(href)
			return href
		}
	}
	return ""
}

// --- subdomain_probe ---

// handleSubdomainProbe is the subdomain_probe handler. DNS-prefilters each
// prefix+year hostname before any HTTP spend.
func handleSubdomainProbe(ctx context.Context, s Source, d *Discovery, state *SourceState, probe *TieredProbe) (confirmed bool) {
	domain := trimRight(trimRight(s.BaseDomain, "."), ".")
	if domain == "" {
		return false
	}
	years := probeYears(s, state.LastConfirmedYear, nowTime())
	if len(years) == 0 {
		return false
	}
	interval := cadenceStep(s)
	prefixes := []string{}
	for _, p := range s.KnownPrefixes {
		if p = trimAll(p); p != "" {
			prefixes = append(prefixes, p)
		}
	}
	confirmedYears := map[int]bool{}

	confirm := func(year int, url string) {
		confirmedYears[year] = true
		if state.LastConfirmedYear == nil || year >= *state.LastConfirmedYear {
			state.LastConfirmedYear = &year
		}
		if d.isNew(url) {
			d.claim(url)
		}
	}

	live := func(url string, year int) bool {
		if !resolves(url) {
			return false
		}
		_, err := probe.verified(ctx, url, year, year-interval)
		return err == nil
	}

	for _, prefix := range prefixes {
		// Tier 1 — liveness for this prefix, newest first (seen or not).
		for _, year := range years {
			url := fmt.Sprintf("https://%s%d.%s", prefix, year, domain)
			if live(url, year) {
				confirm(year, url)
				break
			}
		}
		// Tier 2 — unseen sweep for this prefix.
		for _, year := range years {
			if confirmedYears[year] {
				continue
			}
			url := fmt.Sprintf("https://%s%d.%s", prefix, year, domain)
			if !d.isNew(url) {
				continue
			}
			if live(url, year) {
				confirm(year, url)
			}
		}
		// Tier 3 — bare host as a last resort.
		bare := fmt.Sprintf("https://%s.%s", prefix, domain)
		if !resolves(bare) {
			continue
		}
		for _, year := range years {
			if confirmedYears[year] {
				continue
			}
			if _, err := probe.verified(ctx, bare, year, year-interval); err == nil {
				confirm(year, bare)
				break
			}
		}
	}
	return len(confirmedYears) > 0
}

// --- conf_info_bd ---

// handleConfInfoBD scrapes the aggregator table and claims each conf-link.
func handleConfInfoBD(ctx context.Context, s Source, d *Discovery, probe *TieredProbe) bool {
	url := s.BaseURL
	if url == "" {
		url = "https://conf.info.bd"
	}
	body, err := probe.raw(ctx, url)
	if err != nil || body == "" {
		return false
	}
	before := d.Len()
	for _, href := range extractConfLinks(body) {
		if d.isNew(href) {
			d.claim(href)
		}
	}
	return d.Len() > before || before > 0
}

// extractConfLinks pulls conf.info.bd links (a.conf-link anchors).
func extractConfLinks(html string) []string {
	hrefs := linkRe.FindAllStringSubmatch(html, -1)
	out := []string{}
	for _, m := range hrefs {
		if len(m) < 2 {
			continue
		}
		href := strings.TrimSpace(m[1])
		if strings.Contains(href, "conf-link") {
			continue
		}
		if strings.HasPrefix(href, "http") {
			out = append(out, href)
		}
	}
	return out
}
