package pipeline

import (
	"context"
	"testing"
	"time"

	"confnotifier/internal/extract"
	"confnotifier/internal/store"
)

// fakeExtractor returns canned page text and parses it into a conference.
type fakeExtractor struct {
	text      string
	cond      bool // is_conference
	conf      bool // confidence >= floor
	past      bool // conference in the past
	exhausted bool
}

func (f *fakeExtractor) Extract(ctx context.Context, url string) (string, error) {
	return f.text, nil
}

func (f *fakeExtractor) ExtractConferences(ctx context.Context, pageText, sourceURL string, prev map[string]any, now time.Time, client *extract.Client) (extract.ExtractResult, error) {
	confidence := 0.9
	if !f.conf {
		confidence = 0.5
	}
	out := map[string]any{
		"is_conference": f.cond,
		"title":         "Test Conf 2027",
		"website":       "https://example.org/conf2027",
		"country":       "Bangladesh",
		"city":          "Dhaka",
		"category":      "Computing",
		"description":   "A test conference.",
		"confidence":    confidence,
	}
	if f.past {
		out["date_start"] = "2020-01-01"
		out["date_end"] = "2020-01-05"
	} else {
		out["date_start"] = "2027-06-01"
		out["date_end"] = "2027-06-03"
	}
	out["abstract_deadline"] = map[string]any{"date": "2027-05-01", "context": "Abstract due"}
	out["full_paper_deadline"] = map[string]any{"date": "2027-05-15", "context": "Full paper due"}
	return out, nil
}

func (f *fakeExtractor) DailyExhausted() bool { return f.exhausted }

// fakeStore records save calls and returns a canned result.
type fakeStore struct {
	saved    []map[string]any
	stored   map[string]any
	incRetry int
}

func (s *fakeStore) SaveConference(ctx context.Context, result map[string]any, existingID int) (*store.SaveConferenceResult, error) {
	s.saved = append(s.saved, result)
	return &store.SaveConferenceResult{Success: true, WasInserted: true, ConfID: 42}, nil
}

func (s *fakeStore) StoredSubmissionDeadlines(ctx context.Context, website string) (map[string]any, error) {
	return s.stored, nil
}

func (s *fakeStore) MarkNotified(ctx context.Context, confID int) error { return nil }
func (s *fakeStore) IncrementRetry(ctx context.Context, url string) error {
	s.incRetry++
	return nil
}

type fakeNotifier struct{ notified int }

func (n *fakeNotifier) Notify(ctx context.Context, conf map[string]any) (bool, error) {
	n.notified++
	return true, nil
}

func newTestProcessor(st Store, ext Extractor) *CandidateProcessor {
	return NewCandidateProcessor(st, store.NewConferenceIndex(), nil, nil,
		nil, ext, &RunStats{}, &fakeNotifier{}, nil)
}

func TestProcessSaved(t *testing.T) {
	fe := &fakeExtractor{cond: true, conf: true}
	fs := &fakeStore{}
	cp := newTestProcessor(fs, fe)
	_, outcome := cp.Process(context.Background(), "https://example.org/conf2027")
	if outcome != Saved {
		t.Fatalf("outcome = %v, want SAVED", outcome)
	}
	if len(fs.saved) != 1 {
		t.Fatalf("saved = %d, want 1", len(fs.saved))
	}
}

func TestProcessNotConference(t *testing.T) {
	fe := &fakeExtractor{cond: false}
	cp := newTestProcessor(&fakeStore{}, fe)
	if _, outcome := cp.Process(context.Background(), "https://example.org/x"); outcome != NotConference {
		t.Fatalf("outcome = %v, want NOT_CONFERENCE", outcome)
	}
}

func TestProcessLowConfidence(t *testing.T) {
	fe := &fakeExtractor{cond: true, conf: false}
	cp := newTestProcessor(&fakeStore{}, fe)
	if _, outcome := cp.Process(context.Background(), "https://example.org/x"); outcome != LowConfidence {
		t.Fatalf("outcome = %v, want LOW_CONFIDENCE", outcome)
	}
}

func TestProcessPastConference(t *testing.T) {
	fe := &fakeExtractor{cond: true, conf: true, past: true}
	cp := newTestProcessor(&fakeStore{}, fe)
	if _, outcome := cp.Process(context.Background(), "https://example.org/x"); outcome != PastConference {
		t.Fatalf("outcome = %v, want PAST_CONFERENCE", outcome)
	}
}

func TestProcessTerminalSkipped(t *testing.T) {
	fe := &fakeExtractor{cond: true, conf: true}
	st := &fakeStore{}
	cp := NewCandidateProcessor(st, store.NewConferenceIndex(),
		[]string{"https://example.org/known"}, nil, nil, fe, &RunStats{}, &fakeNotifier{}, nil)
	if _, outcome := cp.Process(context.Background(), "https://example.org/known"); outcome != AlreadyDecided {
		t.Fatalf("outcome = %v, want ALREADY_DECIDED", outcome)
	}
	if len(st.saved) != 0 {
		t.Fatalf("should not save a terminal url")
	}
}

func TestProcessRetryableIncrements(t *testing.T) {
	fe := &fakeExtractor{cond: true, conf: true}
	fs := &fakeStore{}
	cp := NewCandidateProcessor(fs, store.NewConferenceIndex(), nil,
		[]string{"https://example.org/retry"}, nil, fe, &RunStats{}, &fakeNotifier{}, nil)
	if _, outcome := cp.Process(context.Background(), "https://example.org/retry"); outcome != Saved {
		t.Fatalf("outcome = %v, want SAVED", outcome)
	}
	if fs.incRetry != 1 {
		t.Fatalf("IncrementRetry called %d times, want 1", fs.incRetry)
	}
}

func TestLoopStopsOnQuota(t *testing.T) {
	fe := &fakeExtractor{cond: true, conf: true}
	fs := &fakeStore{}
	stats := &RunStats{}
	stats.MarkQuotaExhausted()
	cp := NewCandidateProcessor(fs, store.NewConferenceIndex(), nil, nil,
		nil, fe, stats, &fakeNotifier{}, nil)
	loop := NewLoop(cp, stats, 10, func(rows [][2]string) {}, nil)
	loop.Run(context.Background(), []string{"a", "b", "c"})
	if found := stats.Found(); found != 3 {
		t.Fatalf("found = %d, want 3", found)
	}
	// Quota was exhausted up front, so nothing should be saved.
	if len(fs.saved) != 0 {
		t.Fatalf("should not process any candidate when quota exhausted")
	}
}
