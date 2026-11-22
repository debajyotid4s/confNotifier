package discovery

import (
	"context"
	"io"
	"net/http"
	"strings"
	"testing"
	"time"
)

// fixedRoundTripper answers every request with body, status 200 — so any URL
// (even https://cse2028.kuet.ac.bd) reaches our fake page.
type fixedRoundTripper struct{ body string }

func (rt fixedRoundTripper) RoundTrip(req *http.Request) (*http.Response, error) {
	return &http.Response{
		StatusCode: 200,
		Header:     http.Header{"Content-Type": []string{"text/html"}},
		Body:       io.NopCloser(strings.NewReader(rt.body)),
	}, nil
}

func makeRouteProbe(body string) *TieredProbe {
	client := &http.Client{Transport: fixedRoundTripper{body: body}, Timeout: 5 * time.Second}
	fetcher := &HTTPFetcher{tiers: []httpTier{{client: client, userAgent: userAgent}}}
	return &TieredProbe{http: fetcher, verify: true, cache: map[string][]string{}}
}

// TestHandleSubdomainProbeSeededPrefixProof is the end-to-end proof of gap #2:
// a brand-new subdomain that carries a fresh CFP is discovered ONLY because its
// prefix was seeded into KnownPrefixes. Without the seed the prefix is never
// in the probe loop, so the edition is missed. We override resolves() so the
// fake hostname "resolves" and a RoundTripper serves the page, isolating the
// discovery logic from DNS.
func TestHandleSubdomainProbeSeededPrefixProof(t *testing.T) {
	origResolves := resolves
	resolves = func(url string) bool { return true } // fake DNS for test hostnames
	defer func() { resolves = origResolves }()

	now := time.Date(2028, 4, 1, 0, 0, 0, 0, time.UTC)
	origNow := nowTime
	nowTime = func() time.Time { return now.UTC() }
	defer func() { nowTime = origNow }()

	// A freshly-announced 2028 CFP on cse.kuet.ac.bd.
	body := "<html><head><title>ICCFUU 2028</title></head><body>" +
		"<h1>ICCFUU 2028</h1><p>Abstract deadline: 10 November 2028</p>" +
		"<p>Prior edition 2027</p></body></html>"

	// Seed the prefix, as seedSubdomainPrefixes does for a big-5 domain.
	s := Source{
		Type:       "subdomain_probe",
		Name:       "kuet-subproof",
		BaseDomain: "kuet.ac.bd",
		Cadence:    "annual",
	}
	seedSubdomainPrefixes(&s)
	if !containsStr(s.KnownPrefixes, "cse") {
		t.Fatalf("seedSubdomainPrefixes did not add cse to %v", s.KnownPrefixes)
	}

	// Control: a source WITHOUT the seed never probes cse.
	ctrl := Source{Type: "subdomain_probe", Name: "kuet-control", BaseDomain: "kuet.ac.bd", Cadence: "annual"}
	if containsStr(ctrl.KnownPrefixes, "cse") {
		t.Fatalf("control unexpectedly has cse seeded")
	}

	d := NewDiscovery(nil)
	probe := makeRouteProbe(body)

	// Seeded source MUST claim the new subdomain edition.
	confirmed := handleSubdomainProbe(context.Background(), s, d, &SourceState{}, probe)
	if !confirmed {
		t.Fatalf("seeded subdomain_probe did not confirm the new edition")
	}
	found := false
	for _, r := range d.Rows() {
		if strings.Contains(r[0], "cse") && strings.Contains(r[0], "2028") {
			found = true
		}
	}
	if !found {
		t.Errorf("seeded source claimed rows %v do not include a cse/2028 subdomain", d.Rows())
	}

	// Control source MUST NOT claim anything (cse not in its prefix loop).
	dctrl := NewDiscovery(nil)
	confirmedC := handleSubdomainProbe(context.Background(), ctrl, dctrl, &SourceState{}, probe)
	if confirmedC {
		t.Errorf("control subdomain_probe confirmed an edition it never probed: %v", dctrl.Rows())
	}
}
