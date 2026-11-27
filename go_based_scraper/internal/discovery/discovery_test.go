package discovery

import (
	"testing"
	"time"
)

func TestProbeYearsCadenceSelfAdvancing(t *testing.T) {
	now := time.Date(2026, 6, 1, 0, 0, 0, 0, time.UTC)
	// File last_known_year=2024, confirmed year 2025 -> anchor 2025, window to 2027.
	s := Source{Cadence: "annual", LastKnownYear: ptr(2024)}
	got := probeYears(s, ptr(2025), now)
	want := []int{2027, 2026, 2025}
	if !equalInts(got, want) {
		t.Errorf("probeYears(cadence) = %v, want %v", got, want)
	}
	// If nothing confirmed yet, anchor on the file's last_known_year; window is
	// anchor..current+interval (Python: while y <= year+interval).
	got = probeYears(s, nil, now)
	want = []int{2027, 2026, 2025, 2024}
	if !equalInts(got, want) {
		t.Errorf("probeYears(no state) = %v, want %v", got, want)
	}
}

func TestProbeYearsProbeYearsStaleFallback(t *testing.T) {
	now := time.Date(2026, 6, 1, 0, 0, 0, 0, time.UTC)
	// All configured probe_years in the past -> current window fallback.
	// Python: width = 2 if len(configured) >= 3 else DEFAULT_LOOKAHEAD(1).
	s := Source{ProbeYears: []int{2022, 2023}}
	got := probeYears(s, nil, now)
	want := []int{2027, 2026}
	if !equalInts(got, want) {
		t.Errorf("probeYears(stale) = %v, want %v", got, want)
	}
	// Three+ configured years -> width 2 fallback.
	s = Source{ProbeYears: []int{2020, 2021, 2022}}
	got = probeYears(s, nil, now)
	want = []int{2028, 2027, 2026}
	if !equalInts(got, want) {
		t.Errorf("probeYears(stale-wide) = %v, want %v", got, want)
	}
	// Current probe_years kept, newest first.
	s = Source{ProbeYears: []int{2026, 2027}}
	got = probeYears(s, nil, now)
	want = []int{2027, 2026}
	if !equalInts(got, want) {
		t.Errorf("probeYears(current) = %v, want %v", got, want)
	}
}

func TestOrderCandidates(t *testing.T) {
	cands := []string{"/{year}/", "/?year={year}", ""}
	got := orderCandidates(cands, "/{year}/")
	want := []string{"/{year}/", "/?year={year}", ""}
	if !equalStrings(got, want) {
		t.Errorf("orderCandidates = %v, want %v", got, want)
	}
	// Unknown learned pattern -> unchanged order.
	got = orderCandidates(cands, "/nope/")
	if !equalStrings(got, cands) {
		t.Errorf("orderCandidates(unknown) = %v, want %v", got, cands)
	}
}

func TestVerifyYearIsCurrent(t *testing.T) {
	if !verifyYearIsCurrent("<title>ICCCIT 2027</title> body 2027 once 2026 twice", 2027, 2026) {
		t.Error("title-year should verify")
	}
	// Year outnumbers previous year in body.
	if !verifyYearIsCurrent("2027 2027 2026", 2027, 2026) {
		t.Error("majority-year should verify")
	}
	// Year present but outnumbered by previous -> no verify.
	if verifyYearIsCurrent("2026 2026 2026 2027", 2027, 2026) {
		t.Error("minority-year should not verify")
	}
	if verifyYearIsCurrent("", 2027, 2026) {
		t.Error("empty should not verify")
	}
}

func TestCanonical(t *testing.T) {
	cases := []struct{ in, want string }{
		{"https://www.BUET.AC.BD/dept/", "https://buet.ac.bd/dept"},
		{"http://buet.ac.bd/dept", "https://buet.ac.bd/dept"},
		{"https://buet.ac.bd/dept?x=1&y=2", "https://buet.ac.bd/dept"},
		{"https://buet.ac.bd/dept/", "https://buet.ac.bd/dept"},
	}
	for _, c := range cases {
		if got := canonical(c.in); got != c.want {
			t.Errorf("canonical(%q) = %q, want %q", c.in, got, c.want)
		}
	}
}

func TestDedupSort(t *testing.T) {
	in := []string{"https://buet.ac.bd/a", "https://BUET.AC.BD/a/", "https://iu.ac.bd/b"}
	got := dedupSort(in)
	want := []string{"https://buet.ac.bd/a", "https://iu.ac.bd/b"}
	if !equalStrings(got, want) {
		t.Errorf("dedupSort = %v, want %v", got, want)
	}
}

func TestHostname(t *testing.T) {
	if got := hostname("https://www.buet.ac.bd/dept?x=1"); got != "www.buet.ac.bd" {
		t.Errorf("hostname = %q", got)
	}
}

func TestExpandPath(t *testing.T) {
	if got := expandPath("https://iccit.org.bd", "/{year}/", 2027); got != "https://iccit.org.bd/2027/" {
		t.Errorf("expandPath = %q", got)
	}
}

func TestSeedSubdomainPrefixes(t *testing.T) {
	// Big-5 domain gets seeded.
	s := Source{BaseDomain: "kuet.ac.bd", KnownPrefixes: []string{"www"}}
	seedSubdomainPrefixes(&s)
	for _, p := range []string{"cse", "eee", "ce", "bba"} {
		if !containsStr(s.KnownPrefixes, p) {
			t.Errorf("seedSubdomainPrefixes(kuet) missing %q in %v", p, s.KnownPrefixes)
		}
	}

	// Idempotent: re-running does not duplicate.
	before := len(s.KnownPrefixes)
	seedSubdomainPrefixes(&s)
	if len(s.KnownPrefixes) != before {
		t.Errorf("seedSubdomainPrefixes not idempotent: %v", s.KnownPrefixes)
	}

	// Existing prefixes are preserved, not dropped.
	if !containsStr(s.KnownPrefixes, "www") {
		t.Errorf("seedSubdomainPrefixes dropped existing prefix www")
	}

	// Non-prioritised domain is left untouched.
	other := Source{BaseDomain: "iub.ac.bd", KnownPrefixes: []string{"cse"}}
	seedSubdomainPrefixes(&other)
	if len(other.KnownPrefixes) != 1 || other.KnownPrefixes[0] != "cse" {
		t.Errorf("seedSubdomainPrefixes(iub) mutated %v", other.KnownPrefixes)
	}
}

// TestProbeYearsStaleFallbackSelfAdvances proves the existing stale-fallback
// already probes the current + next year, so a newly-announced edition is
// discovered once a source's configured years go stale. (A separate seedNextYear
// is therefore unnecessary for path_probe.)
func TestProbeYearsStaleFallbackSelfAdvances(t *testing.T) {
	now := time.Date(2028, 1, 1, 0, 0, 0, 0, time.UTC)
	// Configured years all in the past -> stale fallback -> year+1, year.
	s := Source{ProbeYears: []int{2026, 2027}}
	got := probeYears(s, ptr(2027), now)
	if !containsInt(got, 2028) {
		t.Errorf("probeYears(stale) = %v, want it to contain the current year 2028", got)
	}
}
func containsStr(xs []string, want string) bool {
	for _, x := range xs {
		if x == want {
			return true
		}
	}
	return false
}

func containsInt(xs []int, want int) bool {
	for _, x := range xs {
		if x == want {
			return true
		}
	}
	return false
}

func equalInts(a, b []int) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

func equalStrings(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

func ptr(i int) *int { return &i }
