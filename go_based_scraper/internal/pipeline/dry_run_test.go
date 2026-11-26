package pipeline

import (
	"context"
	"io"
	"log"
	"testing"

	"confnotifier/internal/store"
)

// A dry run must still reach the "saved" outcome (so the pipeline is validated)
// but must not persist anything: no SaveConference, no IncrementRetry, no
// Telegram notification.
func TestDryRunDoesNotSave(t *testing.T) {
	fe := &fakeExtractor{cond: true, conf: true}
	fs := &fakeStore{}
	nf := &fakeNotifier{}
	cp := NewCandidateProcessor(fs, store.NewConferenceIndex(), nil, nil,
		nil, fe, &RunStats{}, nf, nil)
	cp.SetDryRun(true)

	_, outcome := cp.Process(context.Background(), "https://example.org/conf2027")
	if outcome != Saved {
		t.Fatalf("dry-run outcome = %v, want SAVED", outcome)
	}
	if len(fs.saved) != 0 {
		t.Fatalf("dry-run must not call SaveConference, got %d calls", len(fs.saved))
	}
	if nf.notified != 0 {
		t.Fatalf("dry-run must not notify, got %d calls", nf.notified)
	}
}

// Dry-run must not bump the retry counter either (that is a DB write).
func TestDryRunRetryNotIncremented(t *testing.T) {
	fe := &fakeExtractor{cond: true, conf: true}
	fs := &fakeStore{}
	cp := NewCandidateProcessor(fs, store.NewConferenceIndex(), nil,
		[]string{"https://example.org/retry"}, nil, fe, &RunStats{}, &fakeNotifier{}, nil)
	cp.SetDryRun(true)

	cp.Process(context.Background(), "https://example.org/retry")
	if fs.incRetry != 0 {
		t.Fatalf("dry-run must not IncrementRetry, got %d", fs.incRetry)
	}
}

// Non-dry run still saves, so the dry-run gating is what changes behaviour.
func TestNormalRunStillSaves(t *testing.T) {
	fe := &fakeExtractor{cond: true, conf: true}
	fs := &fakeStore{}
	cp := NewCandidateProcessor(fs, store.NewConferenceIndex(), nil, nil,
		nil, fe, &RunStats{}, &fakeNotifier{}, nil)
	cp.SetDryRun(false)

	_, outcome := cp.Process(context.Background(), "https://example.org/conf2027")
	if outcome != Saved {
		t.Fatalf("outcome = %v, want SAVED", outcome)
	}
	if len(fs.saved) != 1 {
		t.Fatalf("normal run must save once, got %d", len(fs.saved))
	}
}

// flushSeenLinks in dry-run mode must not touch the DB (nil pool is safe) and
// must not panic.
func TestFlushSeenLinksDryRunNoWrite(t *testing.T) {
	r := &Runner{dryRun: true, pool: nil, logger: log.New(io.Discard, "", 0)}
	r.flushSeenLinks(context.Background(), [][2]string{
		{"https://a.example", "extracted"},
		{"https://b.example", "not_conference"},
	})
}

// flushSeenLinks with an empty row set is a no-op.
func TestFlushSeenLinksEmpty(t *testing.T) {
	r := &Runner{dryRun: false, pool: nil, logger: log.New(io.Discard, "", 0)}
	r.flushSeenLinks(context.Background(), nil)
}
