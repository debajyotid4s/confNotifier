// LoadConferenceIndex builds the in-memory dedup index.
package store

import (
	"context"
	"fmt"
	"log"
	"time"
)

// LoadConferenceIndex builds the in-memory dedup index.
func LoadConferenceIndex(ctx context.Context, p *Pool) (*ConferenceIndex, error) {
	ci := NewConferenceIndex()
	rows, err := p.Query(ctx, conferenceIndexQuery())
	if err != nil {
		return nil, fmt.Errorf("load index: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id int
		var website, title any
		var dateStart any
		dst := []any{&id, &website, &title, &dateStart}
		for range DeadlineTypes {
			dst = append(dst, new(any))
		}
		if err := rows.Scan(dst...); err != nil {
			return nil, fmt.Errorf("scan index row: %w", err)
		}
		ci.Add(id, toString(website), toString(title), toString(dateStart), nil)
	}
	log.Printf("Loaded dedup index: %d website(s), %d edition(s)",
		len(ci.ByURL), len(ci.ByEdition))
	return ci, nil
}

func conferenceIndexQuery() string {
	deadlineCols := ""
	for i, typ := range DeadlineTypes {
		if i > 0 {
			deadlineCols += ", "
		}
		deadlineCols += typ + "_deadline"
	}
	return "SELECT id, website, title, date_start, " + deadlineCols + " FROM conferences"
}

// toString renders a scanned DB value (string, []byte, time.Time) as a string.
func toString(v any) string {
	switch t := v.(type) {
	case string:
		return t
	case []byte:
		return string(t)
	case time.Time:
		return t.Format("2006-01-02")
	default:
		return fmt.Sprintf("%v", t)
	}
}
