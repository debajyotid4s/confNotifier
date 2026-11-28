// Integration tests for the durable outbox, deadline-change audit, and job
// lease. Exercises the real SQL against TEST_DATABASE_URL.
//go:build integration

package store

import (
	"context"
	"testing"
	"time"
)

// --- helpers ---

func sptr(s string) *string { return &s }

func drainOutbox(ctx context.Context, p *Pool) {
	_, _ = p.Exec(ctx, "DELETE FROM outbox")
}

func drainJobLeases(ctx context.Context, p *Pool) {
	_, _ = p.Exec(ctx, "DELETE FROM job_leases")
}

// insertTestConference inserts (or replaces) a conference so deadline-change
// rows have a valid FK target. Returns its id.
func insertTestConference(t *testing.T, ctx context.Context, p *Pool, website string) int {
	t.Helper()
	_, _ = p.Exec(ctx, "DELETE FROM conferences WHERE website = $1", website)
	var id int
	err := p.QueryRow(ctx,
		"INSERT INTO conferences (title, website, date_start) VALUES ($1, $2, $3) RETURNING id",
		"Test Conf "+website, website, time.Date(2027, 1, 1, 0, 0, 0, 0, time.UTC)).Scan(&id)
	if err != nil {
		t.Fatalf("insert test conference: %v", err)
	}
	return id
}

// --- outbox ---

// TestClaimOutboxAtomicSingleWinner: one queued row is claimed by exactly one
// caller; a second claim returns nil. The claim moves the row to 'delivering'.
func TestClaimOutboxAtomicSingleWinner(t *testing.T) {
	ctx := context.Background()
	p := testPool(t)
	drainOutbox(ctx, p)
	defer drainOutbox(ctx, p)

	now := time.Now().UTC()
	id, err := EnqueueOutbox(ctx, p, "digest", "body", nil, sptr("all_users"), nil, nil, nil)
	if err != nil {
		t.Fatalf("enqueue: %v", err)
	}

	row, err := ClaimOutbox(ctx, p, now)
	if err != nil {
		t.Fatalf("claim 1: %v", err)
	}
	if row == nil {
		t.Fatal("first claim should win")
	}
	if row.ID != id || row.Status != outboxDelivering {
		t.Errorf("claimed row = %d/%s, want %d/%s", row.ID, row.Status, id, outboxDelivering)
	}

	row2, err := ClaimOutbox(ctx, p, now)
	if err != nil {
		t.Fatalf("claim 2: %v", err)
	}
	if row2 != nil {
		t.Errorf("second claim = %d, want nil (single winner)", row2.ID)
	}
}

// TestClaimOutboxOldestFirst: the oldest pending row (by created_at) is claimed
// first, so two sequential claims return the rows in enqueue order.
func TestClaimOutboxOldestFirst(t *testing.T) {
	ctx := context.Background()
	p := testPool(t)
	drainOutbox(ctx, p)
	defer drainOutbox(ctx, p)

	now := time.Now().UTC()
	id1, _ := EnqueueOutbox(ctx, p, "digest", "one", nil, sptr("all_users"), nil, nil, nil)
	id2, _ := EnqueueOutbox(ctx, p, "digest", "two", nil, sptr("all_users"), nil, nil, nil)

	row1, _ := ClaimOutbox(ctx, p, now)
	if row1.ID != id1 {
		t.Errorf("first claim = %d, want oldest %d", row1.ID, id1)
	}
	row2, _ := ClaimOutbox(ctx, p, now)
	if row2.ID != id2 {
		t.Errorf("second claim = %d, want %d", row2.ID, id2)
	}
}

// TestFailOutboxRetryable: a failed attempt under budget re-queues the row and
// records a temporary_failure; the outcome is retryable.
func TestFailOutboxRetryable(t *testing.T) {
	ctx := context.Background()
	p := testPool(t)
	drainOutbox(ctx, p)
	defer drainOutbox(ctx, p)

	now := time.Now().UTC()
	id, _ := EnqueueOutbox(ctx, p, "urgent", "body", nil, sptr("all_users"), nil, nil, nil)

	row, err := ClaimOutbox(ctx, p, now)
	if err != nil {
		t.Fatalf("claim: %v", err)
	}
	retryable, err := FailOutbox(ctx, p, row.ID, "FCM 500", now)
	if err != nil {
		t.Fatalf("fail: %v", err)
	}
	// The worker records the audit row for the failed try (separate from the
	// status transition). row.Attempts is the attempt number from ClaimOutbox.
	if err := RecordDeliveryAttempt(ctx, p, row.ID, row.Attempts, attemptTemporaryFailure, "fcm", "", "FCM 500"); err != nil {
		t.Fatalf("record attempt: %v", err)
	}
	if !retryable {
		t.Error("attempt 1 of 3 should be retryable")
	}

	// The row is pending again (re-queued) with a future next_attempt_at, and a
	// temporary_failure attempt row was recorded.
	got, err := selectOutboxStatus(ctx, p, id)
	if err != nil {
		t.Fatalf("status: %v", err)
	}
	if got != outboxPending {
		t.Errorf("status after fail = %s, want pending", got)
	}
	attempts := selectAttemptCounts(ctx, p, id)
	if len(attempts) != 1 || attempts[0] != attemptTemporaryFailure {
		t.Errorf("attempts = %v, want one temporary_failure", attempts)
	}
}

// TestFailOutboxExhausts: once attempts reach max_attempts the row becomes
// 'failed' (dead), is no longer claimable, and every try is recorded.
func TestFailOutboxExhausts(t *testing.T) {
	ctx := context.Background()
	p := testPool(t)
	drainOutbox(ctx, p)
	defer drainOutbox(ctx, p)

	now := time.Now().UTC()
	id, _ := EnqueueOutbox(ctx, p, "urgent", "body", nil, sptr("all_users"), nil, nil, nil)

	// max_attempts defaults to 3: three claim/fail cycles, each re-claiming with
	// a now past the previous backoff.
	var cur = now
	for i := 0; i < 3; i++ {
		row, err := ClaimOutbox(ctx, p, cur)
		if err != nil {
			t.Fatalf("claim %d: %v", i, err)
		}
		if row.ID != id {
			t.Fatalf("claim %d: got %d, want %d", i, row.ID, id)
		}
		retryable, err := FailOutbox(ctx, p, row.ID, "boom", cur)
		if err != nil {
			t.Fatalf("fail %d: %v", i, err)
		}
		if err := RecordDeliveryAttempt(ctx, p, row.ID, row.Attempts, attemptTemporaryFailure, "fcm", "", "boom"); err != nil {
			t.Fatalf("record attempt %d: %v", i, err)
		}
		if i < 2 && !retryable {
			t.Errorf("attempt %d should be retryable", i)
		}
		if i == 2 && retryable {
			t.Error("third attempt should exhaust the budget")
		}
		cur = cur.Add(10 * time.Minute) // clear the (<=9m) backoff for the next re-claim
	}

	got, err := selectOutboxStatus(ctx, p, id)
	if err != nil {
		t.Fatalf("status: %v", err)
	}
	if got != outboxFailed {
		t.Errorf("final status = %s, want failed", got)
	}
	if _, err := ClaimOutbox(ctx, p, cur); err != nil {
		t.Fatalf("claim after fail: %v", err)
	} else if got, _ := selectOutboxStatus(ctx, p, id); got != outboxFailed {
		t.Error("a failed row must never be re-claimed")
	}
	if n := selectAttemptCount(ctx, p, id); n != 3 {
		t.Errorf("attempt count = %d, want 3", n)
	}
}

// TestDeliverSuccess: a delivered row is stamped, and a success attempt is
// recorded.
func TestDeliverSuccess(t *testing.T) {
	ctx := context.Background()
	p := testPool(t)
	drainOutbox(ctx, p)
	defer drainOutbox(ctx, p)

	now := time.Now().UTC()
	id, _ := EnqueueOutbox(ctx, p, "digest", "body", nil, sptr("all_users"), nil, nil, nil)

	row, err := ClaimOutbox(ctx, p, now)
	if err != nil {
		t.Fatalf("claim: %v", err)
	}
	if err := RecordDeliveryAttempt(ctx, p, id, row.Attempts, attemptSuccess, "fcm", "msg-123", ""); err != nil {
		t.Fatalf("record attempt: %v", err)
	}
	if err := MarkOutboxDelivered(ctx, p, id, "msg-123", now); err != nil {
		t.Fatalf("mark delivered: %v", err)
	}

	got, err := selectOutboxStatus(ctx, p, id)
	if err != nil {
		t.Fatalf("status: %v", err)
	}
	if got != outboxDelivered {
		t.Errorf("status = %s, want delivered", got)
	}
	attempts := selectAttemptCounts(ctx, p, id)
	if len(attempts) != 1 || attempts[0] != attemptSuccess {
		t.Errorf("attempts = %v, want one success", attempts)
	}
}

// --- deadline_change_history ---

// TestDeadlineChangeRecordAndQuery: recorded moves are returned newest-first,
// and a Since filter trims older entries.
func TestDeadlineChangeRecordAndQuery(t *testing.T) {
	ctx := context.Background()
	p := testPool(t)
	confID := insertTestConference(t, ctx, p, "https://example.com/dc-conf")
	defer func() { _, _ = p.Exec(ctx, "DELETE FROM conferences WHERE id = $1", confID) }()

	base := time.Date(2027, 5, 1, 12, 0, 0, 0, time.UTC)

	if err := RecordDeadlineChange(ctx, p, DeadlineChange{
		ConferenceID: confID, DeadlineType: "abstract",
		OldDate: ptrTime(base), NewDate: ptrTime(base.Add(48 * time.Hour)),
		OldLabel: sptr("Feb 01"), NewLabel: sptr("Feb 03"), DetectedBy: "verify_deadlines",
	}); err != nil {
		t.Fatalf("record 1: %v", err)
	}
	if err := RecordDeadlineChange(ctx, p, DeadlineChange{
		ConferenceID: confID, DeadlineType: "full_paper",
		NewDate: ptrTime(base.Add(96 * time.Hour)), DetectedBy: "scraper",
	}); err != nil { // first-time discovery, no old date
		t.Fatalf("record 2: %v", err)
	}

	all, err := DeadlineChangesSince(ctx, p, confID, nil)
	if err != nil {
		t.Fatalf("query: %v", err)
	}
	if len(all) != 2 {
		t.Fatalf("got %d changes, want 2", len(all))
	}
	if all[0].DeadlineType != "full_paper" {
		t.Errorf("newest = %s, want full_paper (recorded last)", all[0].DeadlineType)
	}
	if all[1].OldDate == nil {
		t.Error("the first-time discovery should have a nil OldDate")
	}

	// Backdate the first (abstract) record so the Since filter has a gap to
	// trim: the abstract move is old, the full_paper move is current.
	_, _ = p.Exec(ctx,
		"UPDATE deadline_change_history SET detected_at = NOW() - interval '2 hours' "+
			"WHERE conference_id = $1 AND deadline_type = 'abstract'", confID)

	// A Since filter between the two records returns only the newer one.
	since := time.Now().UTC().Add(-30 * time.Minute)
	recent, err := DeadlineChangesSince(ctx, p, confID, &since)
	if err != nil {
		t.Fatalf("query since: %v", err)
	}
	if len(recent) != 1 || recent[0].DeadlineType != "full_paper" {
		t.Errorf("since filter returned %d, want just full_paper", len(recent))
	}
}

// --- job_leases ---

// TestJobLeaseSingleInstance: one owner per job name; a second owner loses until
// the holder releases.
func TestJobLeaseSingleInstance(t *testing.T) {
	ctx := context.Background()
	p := testPool(t)
	drainJobLeases(ctx, p)
	defer drainJobLeases(ctx, p)

	ok, err := AcquireJobLease(ctx, p, "digest", "owner-a")
	if err != nil {
		t.Fatalf("acquire a: %v", err)
	}
	if !ok {
		t.Fatal("first acquire should win")
	}
	ok, err = AcquireJobLease(ctx, p, "digest", "owner-b")
	if err != nil {
		t.Fatalf("acquire b: %v", err)
	}
	if ok {
		t.Error("second acquire should lose (fresh holder)")
	}

	held, _ := JobLeaseHeld(ctx, p, "digest")
	if !held {
		t.Error("lease should be held")
	}

	if err := RefreshJobLease(ctx, p, "digest", "owner-a"); err != nil {
		t.Fatalf("refresh: %v", err)
	}
	// A refresh by a non-holder is a safe no-op: it must not steal or change the
	// lease, which stays owned by owner-a.
	if err := RefreshJobLease(ctx, p, "digest", "owner-b"); err != nil {
		t.Fatalf("refresh (non-holder): %v", err)
	}
	if owner := selectJobLeaseOwner(ctx, p, "digest"); owner != "owner-a" {
		t.Errorf("owner after non-holder refresh = %q, want owner-a", owner)
	}

	if err := ReleaseJobLease(ctx, p, "digest", "owner-a"); err != nil {
		t.Fatalf("release: %v", err)
	}
	held, _ = JobLeaseHeld(ctx, p, "digest")
	if held {
		t.Error("lease should be free after release")
	}
	ok, err = AcquireJobLease(ctx, p, "digest", "owner-b")
	if err != nil || !ok {
		t.Fatalf("acquire after release: ok=%v err=%v", ok, err)
	}
}

// TestReclaimStaleJobLeases: a lease whose expires_at has passed is reclaimed
// (owner cleared) and becomes acquirable by anyone.
func TestReclaimStaleJobLeases(t *testing.T) {
	ctx := context.Background()
	p := testPool(t)
	drainJobLeases(ctx, p)
	defer drainJobLeases(ctx, p)

	if ok, err := AcquireJobLease(ctx, p, "verify", "owner-x"); err != nil || !ok {
		t.Fatalf("acquire: ok=%v err=%v", ok, err)
	}
	// Backdate the expiry so the lease is stale.
	_, _ = p.Exec(ctx,
		"UPDATE job_leases SET expires_at = NOW() - interval '1 hour' WHERE job_name = $1", "verify")

	reclaimed, err := ReclaimStaleJobLeases(ctx, p)
	if err != nil {
		t.Fatalf("reclaim: %v", err)
	}
	found := false
	for _, n := range reclaimed {
		if n == "verify" {
			found = true
		}
	}
	if !found {
		t.Errorf("reclaimed = %v, want 'verify'", reclaimed)
	}

	ok, err := AcquireJobLease(ctx, p, "verify", "owner-y")
	if err != nil || !ok {
		t.Fatalf("acquire after reclaim: ok=%v err=%v", ok, err)
	}
}

// --- small selectors used by the tests above ---

func selectOutboxStatus(ctx context.Context, p *Pool, id int64) (string, error) {
	var status string
	if err := p.QueryRow(ctx, "SELECT status FROM outbox WHERE id = $1", id).Scan(&status); err != nil {
		return "", err
	}
	return status, nil
}

func selectAttempts(ctx context.Context, p *Pool, outboxID int64) ([]string, error) {
	rows, err := p.Query(ctx, "SELECT status FROM delivery_attempts WHERE outbox_id = $1 ORDER BY attempt", outboxID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []string
	for rows.Next() {
		var s string
		if err := rows.Scan(&s); err != nil {
			return nil, err
		}
		out = append(out, s)
	}
	return out, rows.Err()
}

// selectJobLeaseOwner returns the current owner of a lease, or "" if none.
func selectJobLeaseOwner(ctx context.Context, p *Pool, jobName string) string {
	var owner string
	err := p.QueryRow(ctx, "SELECT owner FROM job_leases WHERE job_name = $1", jobName).Scan(&owner)
	if err != nil {
		return ""
	}
	return owner
}

func selectAttemptCount(ctx context.Context, p *Pool, outboxID int64) int {
	attempts, err := selectAttempts(ctx, p, outboxID)
	if err != nil {
		return 0
	}
	return len(attempts)
}

func selectAttemptCounts(ctx context.Context, p *Pool, outboxID int64) []string {
	attempts, err := selectAttempts(ctx, p, outboxID)
	if err != nil {
		return nil
	}
	return attempts
}

// ptrTime is a *time.Time helper for the audit-trail tests.
func ptrTime(t time.Time) *time.Time { return &t }
