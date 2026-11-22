package discovery

import (
	"encoding/json"
	"os"
	"path/filepath"
	"time"
)

// Source is one entry from config/sources.json. The type identity decides how
// its live URL(s) are built (see buildURLs). Mirrors scraper/sources/config.py
// + scraper/sources/urls.py.
type Source struct {
	Type          string   `json:"type"`
	Name          string   `json:"name"`
	BaseURL       string   `json:"base_url"`
	BaseDomain    string   `json:"base_domain"`
	Candidates    []string `json:"candidates"`
	ProbeYears    []int    `json:"probe_years"`
	KnownPrefixes []string `json:"known_prefixes"`
	Cadence       string   `json:"cadence"`
	LastKnownYear *int     `json:"last_known_year"`
	VerifyYear    bool     `json:"verify_year_in_content"`
	DiscoverLinks bool     `json:"discover_links"`
}

// LoadSources reads the unified discovery config. It merges two files so the
// loader stays compatible with the on-disk split: config/sources.json holds the
// "regular" university homepages and config/specials.json holds the
// "path_probe" / "subdomain_probe" / "conf_info_bd" entries. The merged slice is
// returned in sources.json order followed by specials.json order.
//
// The config directory is resolved relative to the current working directory,
// searching upward through parent directories so the scraper works whether it
// is launched from the repo root or from go_based_scraper/. A missing or
// malformed file degrades to "no sources from that file" rather than aborting.
func LoadSources(path string) []Source {
	cfgDir := configDir()
	sources := readSourcesFile(filepath.Join(cfgDir, "config", "sources.json"))
	specials := readSourcesFile(filepath.Join(cfgDir, "config", "specials.json"))
	return append(sources, specials...)
}

// configDir locates the config/ directory holding sources.json and
// specials.json, searching the current working directory and its parents so the
// scraper runs from either the repo root or go_based_scraper/.
func configDir() string {
	dir, err := os.Getwd()
	if err != nil {
		dir = "."
	}
	for {
		if _, err := os.Stat(filepath.Join(dir, "config", "sources.json")); err == nil {
			return dir
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return "."
		}
		dir = parent
	}
}

// readSourcesFile parses one config file into Source entries, returning nil on
// any error (missing file, bad JSON, wrong shape).
func readSourcesFile(path string) []Source {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	var sources []Source
	if err := json.Unmarshal(data, &sources); err != nil {
		return nil
	}
	return sources
}

// RegularDomains returns the base_url of every "regular" source, in order.
func RegularDomains(sources []Source) []string {
	var out []string
	for _, s := range sources {
		if s.Type == "regular" && s.BaseURL != "" {
			out = append(out, s.BaseURL)
		}
	}
	return out
}

// cadenceStep is the edition interval in years for a cadenced source.
func cadenceStep(s Source) int {
	switch s.Cadence {
	case "biennial":
		return 2
	case "triennial":
		return 3
	default:
		return 1
	}
}

// currentYear is the edition year considered "now" (injectable for tests).
func currentYear(now time.Time) int {
	return now.Year()
}

// likelyCfpPrefixes are department/faculty hostnames that commonly host a
// conference or CFP on a university domain.
var likelyCfpPrefixes = []string{
	"cse", "eee", "me", "ce", "iee", "bba", "ee", "pme",
	"uob", "business", "engineering", "mba", "ibm", "rfd",
}

// isBigUniversity reports whether a domain is one the scraper prioritises for
// proactive subdomain seeding.
func isBigUniversity(domain string) bool {
	switch domain {
	case "kuet.ac.bd", "mist.ac.bd", "buet.ac.bd", "bracu.ac.bd", "sust.edu":
		return true
	}
	return false
}

// seedSubdomainPrefixes adds any unseeded likely-CFP hostnames to a
// subdomain_probe source for a prioritised university, so future editions on
// those subdomains are probed even before link-discovery has seen them.
func seedSubdomainPrefixes(s *Source) {
	domain := trimRight(trimRight(s.BaseDomain, "."), ".")
	if !isBigUniversity(domain) {
		return
	}
	existing := map[string]bool{}
	for _, p := range s.KnownPrefixes {
		existing[trimAll(p)] = true
	}
	for _, p := range likelyCfpPrefixes {
		if !existing[p] {
			s.KnownPrefixes = append(s.KnownPrefixes, p)
		}
	}
}

// probeYears returns the years to probe for a source, newest first.
// For cadenced sources the anchor is whichever is newer — the file's static
// last_known_year or a year the code has since confirmed — and the window
// extends exactly one cycle past the current year, so it stays small forever.
// For probe_years sources, stale entries are voided with a current-window
// fallback.
func probeYears(s Source, lastConfirmed *int, now time.Time) []int {
	year := currentYear(now)
	if s.Cadence != "" && s.LastKnownYear != nil {
		interval := cadenceStep(s)
		anchor := *s.LastKnownYear
		if lastConfirmed != nil && *lastConfirmed > anchor {
			anchor = *lastConfirmed
		}
		var years []int
		for y := anchor; y <= year+interval; y += interval {
			years = append(years, y)
		}
		return reverse(years)
	}
	live := []int{}
	for _, y := range s.ProbeYears {
		if y >= year {
			live = append(live, y)
		}
	}
	if len(live) > 0 {
		return reverse(live)
	}
	// Stale configured years: fall back to a small current window.
	width := 2
	if len(s.ProbeYears) < 3 {
		width = 1
	}
	out := []int{}
	for i := width; i >= 0; i-- {
		out = append(out, year+i)
	}
	return out
}

// orderCandidates puts the learned working_candidate first, keeping the rest in
// declared order. Once a pattern wins once, every future run tries it first.
func orderCandidates(candidates []string, workingCandidate string) []string {
	if workingCandidate == "" {
		return candidates
	}
	out := []string{}
	if contains(candidates, workingCandidate) {
		out = append(out, workingCandidate)
	}
	for _, c := range candidates {
		if c != workingCandidate {
			out = append(out, c)
		}
	}
	return out
}

func reverse(in []int) []int {
	out := make([]int, len(in))
	for i, v := range in {
		out[len(in)-1-i] = v
	}
	return out
}

func contains(in []string, v string) bool {
	for _, s := range in {
		if s == v {
			return true
		}
	}
	return false
}

func replaceAll(s, old, new string) string {
	out := ""
	for {
		i := index(s, old)
		if i < 0 {
			out += s
			break
		}
		out += s[:i] + new
		s = s[i+len(old):]
	}
	return out
}

func index(s, sub string) int {
	for i := 0; i+len(sub) <= len(s); i++ {
		if s[i:i+len(sub)] == sub {
			return i
		}
	}
	return -1
}

func trimRight(s, cut string) string {
	for len(s) > len(cut) && hasSuffix(s, cut) {
		s = s[:len(s)-len(cut)]
	}
	return s
}

func hasSuffix(s, suffix string) bool {
	return len(s) >= len(suffix) && s[len(s)-len(suffix):] == suffix
}

func trimAll(s string) string {
	start, end := 0, len(s)
	for start < end && (s[start] == ' ' || s[start] == '\t') {
		start++
	}
	for end > start && (s[end-1] == ' ' || s[end-1] == '\t') {
		end--
	}
	return s[start:end]
}

func itoa(i int) string {
	if i == 0 {
		return "0"
	}
	neg := i < 0
	if neg {
		i = -i
	}
	var buf [20]byte
	pos := len(buf)
	for i > 0 {
		pos--
		buf[pos] = byte('0' + i%10)
		i /= 10
	}
	if neg {
		pos--
		buf[pos] = '-'
	}
	return string(buf[pos:])
}
