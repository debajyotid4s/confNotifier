package discovery

import (
	"context"

	"confnotifier/internal/store"
)

// StateStore persists the learned per-source resolver state (the dynamic half
// alongside the static config/sources.json). It fails open: a DB error leaves
// state empty so discovery still runs, just without learning.
type StateStore interface {
	LoadAll(ctx context.Context) map[string]*SourceState
	SaveAll(ctx context.Context, changed map[string]*SourceState) (int, error)
}

// SourceState is one source's learned state. Mirrors
// scraper/sources/state.py + store.SourceState.
type SourceState struct {
	Name              string
	LastConfirmedYear *int
	WorkingCandidate  string
	ConsecutiveFail   int
}

// Clone returns a copy so callers can mutate without touching the store.
func (s *SourceState) Clone() *SourceState {
	c := *s
	return &c
}

// DbStateStore is the Postgres-backed store. It fails open.
type DbStateStore struct{ pool *store.Pool }

// NewStateStore builds a StateStore over the given pool.
func NewStateStore(p *store.Pool) DbStateStore {
	return DbStateStore{pool: p}
}

// LoadAll returns learned state keyed by source name, empty on error.
func (s DbStateStore) LoadAll(ctx context.Context) map[string]*SourceState {
	states, err := store.LoadSourceStates(ctx, s.pool)
	if err != nil {
		return map[string]*SourceState{}
	}
	out := make(map[string]*SourceState, len(states))
	for _, ss := range states {
		out[ss.Name] = &SourceState{
			Name:              ss.Name,
			LastConfirmedYear: ss.LastConfirmedYear,
			WorkingCandidate:  ss.WorkingCandidate,
			ConsecutiveFail:   ss.ConsecutiveFail,
		}
	}
	return out
}

// SaveAll upserts changed state in one batch, returning the row count.
func (s DbStateStore) SaveAll(ctx context.Context, changed map[string]*SourceState) (int, error) {
	if len(changed) == 0 {
		return 0, nil
	}
	names := make([]string, 0, len(changed))
	for name := range changed {
		names = append(names, name)
	}
	values := make([][]any, 0, len(names))
	for _, name := range names {
		st := changed[name]
		values = append(values, []any{
			name, st.LastConfirmedYear, st.WorkingCandidate, st.ConsecutiveFail,
		})
	}
	return store.UpsertSourceStates(ctx, s.pool, values)
}

// snapshot returns a deep copy of state for change detection.
func snapshot(states map[string]*SourceState) map[string]*SourceState {
	out := make(map[string]*SourceState, len(states))
	for name, st := range states {
		out[name] = st.Clone()
	}
	return out
}

// changedStates returns the states that differ from their snapshot.
func changedStates(states, snapshot map[string]*SourceState) map[string]*SourceState {
	out := map[string]*SourceState{}
	for name, st := range states {
		prev := snapshot[name]
		if prev == nil || *prev != *st {
			out[name] = st
		}
	}
	return out
}
