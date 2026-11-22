package notify

import (
	"context"
	"fmt"
	"sync"
	"testing"
	"time"
)

// fakeNotifier records MarkNotified calls.
type fakeNotifier struct {
	mu        sync.Mutex
	marked    []int
	failAfter int
}

func (f *fakeNotifier) MarkNotified(_ context.Context, id int) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.failAfter > 0 && len(f.marked) >= f.failAfter {
		return fmt.Errorf("db down")
	}
	f.marked = append(f.marked, id)
	return nil
}

// fakePending returns a fixed set of rows.
type fakePending struct {
	rows []PendingRow
}

func (f fakePending) LoadPending(context.Context) ([]PendingRow, error) {
	return f.rows, nil
}

func TestPendingSweepNotifiesOnlyOnSuccess(t *testing.T) {
	pending := fakePending{rows: []PendingRow{
		{ID: 1, Title: "A", Website: "https://a.edu", DateStart: "2027-05-01",
			Deadlines: []DeadlinePair{{Type: "abstract", Date: "2027-02-01", Label: "Abstract"}}},
		{ID: 2, Title: "B", Website: "https://b.edu", DateStart: "2027-05-01",
			Deadlines: []DeadlinePair{{Type: "abstract", Date: "2027-02-01", Label: "Abstract"}}},
	}}
	notif := &fakeNotifier{}
	// Second post returns 0 (failure): only id 1 is marked notified.
	notifyFn := func(_ context.Context, conf map[string]any) (int, error) {
		if conf["website"] == "https://b.edu" {
			return 0, nil
		}
		return 7, nil
	}
	got := PendingSweep(context.Background(), pending, notif, notifyFn, 0)
	if got != 1 {
		t.Errorf("expected 1 sent, got %d", got)
	}
	notif.mu.Lock()
	defer notif.mu.Unlock()
	if len(notif.marked) != 1 || notif.marked[0] != 1 {
		t.Errorf("expected only id 1 marked, got %v", notif.marked)
	}
}

func TestPendingSweepEmpty(t *testing.T) {
	notif := &fakeNotifier{}
	got := PendingSweep(context.Background(), fakePending{nil}, notif,
		func(context.Context, map[string]any) (int, error) { return 1, nil }, 0)
	if got != 0 {
		t.Errorf("expected 0 for empty queue")
	}
	_ = notif
}

func TestPendingSweepMarksAfterSend(t *testing.T) {
	pending := fakePending{rows: []PendingRow{
		{ID: 5, Title: "A", Website: "https://a.edu", DateStart: "2027-05-01",
			Deadlines: []DeadlinePair{{Type: "abstract", Date: "2027-02-01", Label: "Abstract"}}},
	}}
	notif := &fakeNotifier{}
	got := PendingSweep(context.Background(), pending, notif,
		func(context.Context, map[string]any) (int, error) { return 1, nil }, 0)
	if got != 1 || len(notif.marked) != 1 || notif.marked[0] != 5 {
		t.Errorf("expected id 5 marked, got sent=%d marked=%v", got, notif.marked)
	}
}

func TestSendMulticastShardsAndCounts(t *testing.T) {
	_ = 0
	fake := func(_ context.Context, batches []PushBatch) ([]PushResult, error) {
		if len(batches) != 3 {
			t.Errorf("expected 3 batches for 1200 tokens, got %d", len(batches))
		}
		for _, b := range batches {
			if len(b.Tokens) > FCMBatch {
				t.Errorf("batch too big: %d", len(b.Tokens))
			}
		}
		return []PushResult{{Sent: 100, Dead: []string{"x"}}, {Sent: 150, Dead: []string{"y", "z"}}}, nil
	}
	sent, dead := SendMulticast(context.Background(), pusherFunc(fake),
		make([]string, 1200), "T", "B", map[string]string{"type": "reminder"})
	if sent != 250 {
		t.Errorf("expected 250 sent, got %d", sent)
	}
	if len(dead) != 3 {
		t.Errorf("expected 3 dead, got %d", len(dead))
	}
}

func TestSendMulticastEmpty(t *testing.T) {
	sent, dead := SendMulticast(context.Background(), pusherFunc(func(context.Context, []PushBatch) ([]PushResult, error) {
		t.Error("should not be called")
		return nil, nil
	}), nil, "T", "B", nil)
	if sent != 0 || len(dead) != 0 {
		t.Errorf("expected 0/0, got %d/%v", sent, dead)
	}
}

func TestDeadTokens(t *testing.T) {
	results := []PushResult{{Sent: 1, Dead: []string{"a", "b"}}, {Sent: 2, Dead: []string{"c"}}}
	if got := DeadTokens(results); len(got) != 3 {
		t.Errorf("expected 3 dead tokens, got %d", len(got))
	}
}

func TestRenderRemindersOrderingAndContent(t *testing.T) {
	d1 := time.Date(2027, 8, 20, 0, 0, 0, 0, time.UTC)
	d2 := time.Date(2027, 8, 10, 0, 0, 0, 0, time.UTC)
	// d1 is urgent-ish (far out), d2 sooner. Just assert sort + markers.
	msg := renderReminders([]reminderEntry{
		{deadline: d1, website: "https://a.edu", title: "Conf A"},
		{deadline: d2, website: "https://b.edu", title: "Conf B", previous: &d1},
	}, time.Now())
	if indexOf(msg, "Conf B") > indexOf(msg, "Conf A") {
		t.Error("entries not sorted by deadline")
	}
	if !contains(msg, "UPCOMING DEADLINES") || !contains(msg, "Updated") {
		t.Error("missing expected markers")
	}
}

// pusherFunc adapts a function to the Pusher interface.
type pusherFunc func(context.Context, []PushBatch) ([]PushResult, error)

func (f pusherFunc) Multicast(ctx context.Context, b []PushBatch) ([]PushResult, error) {
	return f(ctx, b)
}
