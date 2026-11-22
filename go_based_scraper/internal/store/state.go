// Domain strategies and source state.
package store

import (
	"context"
	"fmt"
)

// DomainStrategy holds a domain's fetch strategy.
type DomainStrategy struct {
	Domain    string
	Strategy  string
	LoadedURL string
}

// LoadDomainStrategies returns cached fetch tier per domain.
func LoadDomainStrategies(ctx context.Context, p *Pool) (map[string]DomainStrategy, error) {
	m := make(map[string]DomainStrategy)
	rows, err := p.Query(ctx, "SELECT domain, strategy, loaded_url FROM domain_strategies")
	if err != nil {
		return nil, fmt.Errorf("load strategies: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var ds DomainStrategy
		if err := rows.Scan(&ds.Domain, &ds.Strategy, &ds.LoadedURL); err != nil {
			return nil, fmt.Errorf("scan strategy: %w", err)
		}
		m[ds.Domain] = ds
	}
	return m, nil
}

// SaveDomainStrategy remembers which fetch tier worked.
func SaveDomainStrategy(ctx context.Context, p *Pool, domain, strategy, loadedURL string) error {
	_, err := p.Exec(ctx,
		"INSERT INTO domain_strategies (domain, strategy, loaded_url) VALUES ($1, $2, $3) "+
			"ON CONFLICT (domain) DO UPDATE SET strategy = EXCLUDED.strategy, "+
			"loaded_url = EXCLUDED.loaded_url, updated_at = NOW()",
		domain, strategy, loadedURL)
	return err
}

// LoadSourceStates returns learned resolver state keyed by source name.
func LoadSourceStates(ctx context.Context, p *Pool) ([]SourceState, error) {
	rows, err := p.Query(ctx,
		"SELECT name, last_confirmed_year, working_candidate, consecutive_failures FROM source_state")
	if err != nil {
		return nil, fmt.Errorf("load source states: %w", err)
	}
	defer rows.Close()
	var out []SourceState
	for rows.Next() {
		var ss SourceState
		if err := rows.Scan(&ss.Name, &ss.LastConfirmedYear, &ss.WorkingCandidate, &ss.ConsecutiveFail); err != nil {
			return nil, fmt.Errorf("scan source state: %w", err)
		}
		out = append(out, ss)
	}
	return out, nil
}

// UpsertSourceStates writes changed source state in one batch. The caller must
// supply the state values via SourceStateValues.
func UpsertSourceStates(ctx context.Context, p *Pool, values [][]any) (int, error) {
	if len(values) == 0 {
		return 0, nil
	}
	placeholders := ""
	for i := range values {
		if i > 0 {
			placeholders += ", "
		}
		placeholders += fmt.Sprintf("($%d, $%d, $%d, $%d)",
			i*4+1, i*4+2, i*4+3, i*4+4)
	}
	_, err := p.Exec(ctx,
		"INSERT INTO source_state (name, last_confirmed_year, working_candidate, consecutive_failures) "+
			"VALUES "+placeholders+" ON CONFLICT (name) DO UPDATE SET "+
			"last_confirmed_year = EXCLUDED.last_confirmed_year, "+
			"working_candidate = EXCLUDED.working_candidate, "+
			"consecutive_failures = EXCLUDED.consecutive_failures, "+
			"updated_at = NOW()",
		flat(values)...)
	return len(values), err
}

// flat flattens [][]any into a single slice for Exec.
func flat(in [][]any) []any {
	out := make([]any, 0, len(in)*4)
	for _, row := range in {
		out = append(out, row...)
	}
	return out
}
