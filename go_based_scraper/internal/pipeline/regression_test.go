package pipeline

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"

	"confnotifier/internal/conf"
	"confnotifier/internal/store"
)

// fixture is one regression case from regression/fixtures.json.
type priorDB struct {
	Exists       bool    `json:"exists"`
	ConferenceID int     `json:"conference_id"`
	Website      *string `json:"website"`
	Title        *string `json:"title"`
	DateStart    *string `json:"date_start"`
}

type fixture struct {
	ID    string `json:"id"`
	Input struct {
		URL     string  `json:"url"`
		PriorDB priorDB `json:"prior_db"`
	} `json:"input"`
	Expected struct {
		Accepted        bool   `json:"accepted"`
		RejectReason    string `json:"reject_reason"`
		ReportedWebsite string `json:"reported_website"`
		DBDecision      string `json:"db_decision"`
	} `json:"expected"`
	Cost struct {
		LLMRequests int `json:"llm_requests"`
	} `json:"cost"`
}

func deref(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}

// loadFixtures reads the regression oracle. Path is relative to the repo root.
func loadFixtures(t *testing.T) []fixture {
	t.Helper()
	// test lives in go_based_scraper/internal/pipeline; fixtures at <root>/regression.
	root := filepath.Join("..", "..", "..")
	data, err := os.ReadFile(filepath.Join(root, "regression", "fixtures.json"))
	if err != nil {
		t.Fatalf("read fixtures: %v", err)
	}
	var fx []fixture
	if err := json.Unmarshal(data, &fx); err != nil {
		t.Fatalf("parse fixtures: %v", err)
	}
	return fx
}

// urlPrecheckReasons are the cheap, URL-level signals that let Go reject a
// candidate WITHOUT spending an LLM call. A reject whose reason is in this set
// matches the Python reference's no-cost rejection path.
var urlPrecheckReasons = map[string]bool{
	"empty": true, "bad_scheme": true, "unparseable": true, "no_host": true,
	"blocked_host": true, "non_html": true, "junk_segment": true, "stale_wording": true,
	"stale_year": true, "no_signal": true, "weak_signal_no_year": true,
}

// TestRegressionFixturesURLPrecheck asserts the single most important, fully
// deterministic parity point: Go classifies every candidate URL exactly as the
// Python reference does — accepting the six CFPs and rejecting the false
// positive and stale-year URLs at the URL precheck.
func TestRegressionFixturesURLPrecheck(t *testing.T) {
	now := time.Date(2026, 11, 27, 0, 0, 0, 0, time.UTC)
	for _, fx := range loadFixtures(t) {
		accepted, reason := conf.ClassifyLink(fx.Input.URL, now)
		if accepted != fx.Expected.Accepted {
			t.Errorf("%s: ClassifyLink accepted=%v reason=%q, want accepted=%v",
				fx.ID, accepted, reason, fx.Expected.Accepted)
		}
		if !fx.Expected.Accepted && fx.Expected.RejectReason != "" && reason != fx.Expected.RejectReason {
			t.Errorf("%s: reject reason=%q, want %q", fx.ID, reason, fx.Expected.RejectReason)
		}
	}
}

// TestRegressionFixturesCheapRejection guards the cost objective: a rejected
// candidate must be rejected at the URL precheck, so the Go implementation
// spends zero LLM requests on it — matching the Python reference.
func TestRegressionFixturesCheapRejection(t *testing.T) {
	for _, fx := range loadFixtures(t) {
		if fx.Expected.Accepted {
			continue
		}
		if _, reason := conf.ClassifyLink(fx.Input.URL, time.Now()); !urlPrecheckReasons[reason] {
			t.Errorf("%s: reject reason %q is not a cheap URL-level signal (would spend an LLM call)",
				fx.ID, reason)
		}
		if fx.Cost.LLMRequests != 0 {
			t.Errorf("%s: reject case expects 0 LLM requests, fixture says %d", fx.ID, fx.Cost.LLMRequests)
		}
	}
}

// TestRegressionFixturesDedupSpine checks the deterministic dedup index against
// the prior DB state: an insert case's reported website is absent (new row),
// while a known URL is present (Go dedups it in discovery). Edition-merge
// (case 5) and resolver re-discovery (case 6) are Python-oracle behaviors that
// the resolver owns; they are verified in the live shadow comparison (Layer 2).
func TestRegressionFixturesDedupSpine(t *testing.T) {
	for _, fx := range loadFixtures(t) {
		if !fx.Expected.Accepted {
			continue
		}
		ci := store.NewConferenceIndex()
		pr := fx.Input.PriorDB
		if pr.Exists {
			ci.Add(pr.ConferenceID, deref(pr.Website), deref(pr.Title), deref(pr.DateStart), nil)
		}
		reported := fx.Expected.ReportedWebsite
		if reported == "" {
			reported = fx.Input.URL
		}
		existing := ci.FindByUrl(reported)
		switch fx.Expected.DBDecision {
		case "insert":
			if existing != 0 {
				t.Errorf("%s: reported website %s already in index, want insert (dedup hit)", fx.ID, reported)
			}
		case "update":
			if existing == 0 {
				t.Errorf("%s: reported website %s missing from index, want update (known URL)", fx.ID, reported)
			}
		}
	}
}
