package pipeline

import (
	"context"

	"confnotifier/internal/store"
)

// poolStore adapts the package-level store functions onto the Store interface
// the processor depends on, so a *store.Pool satisfies it directly.
type poolStore struct{ p *store.Pool }

func (s poolStore) SaveConference(ctx context.Context, result map[string]any, existingID int) (*store.SaveConferenceResult, error) {
	return store.SaveConference(ctx, s.p, result, existingID)
}

func (s poolStore) StoredSubmissionDeadlines(ctx context.Context, website string) (map[string]any, error) {
	return store.StoredSubmissionDeadlines(ctx, s.p, website)
}

func (s poolStore) MarkNotified(ctx context.Context, confID int) error {
	return store.MarkNotified(ctx, s.p, confID)
}

func (s poolStore) IncrementRetry(ctx context.Context, url string) error {
	return store.IncrementRetry(ctx, s.p, url)
}

// newPoolStore returns a Store backed by the given pool.
func newPoolStore(p *store.Pool) Store { return poolStore{p} }
