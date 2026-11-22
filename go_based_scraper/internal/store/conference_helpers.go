// Conference SQL helpers: columns, values, clauses.
package store

import (
	"fmt"
	"strings"
)

func baseColumns() []string {
	return []string{"title", "date_start", "date_end", "city", "country",
		"website", "organizer", "category", "description", "confidence", "raw_source", "is_notified"}
}

func baseValues(conf map[string]any, website string) []any {
	return []any{
		confStr(conf, "title"), confStr(conf, "date_start"),
		confStr(conf, "date_end"), confStr(conf, "city"),
		confStr(conf, "country"), website, confStr(conf, "organizer"),
		confStr(conf, "category"), confStr(conf, "description"),
		confFloat(conf, "confidence"), confStr(conf, "raw_source"), false,
	}
}

func confStr(conf map[string]any, key string) string {
	v, _ := conf[key].(string)
	return v
}

func confFloat(conf map[string]any, key string) float32 {
	v, _ := conf[key].(float64)
	return float32(v)
}

func params(n int) string {
	parts := make([]string, n)
	for i := range parts {
		parts[i] = fmt.Sprintf("$%d", i+1)
	}
	return strings.Join(parts, ", ")
}

func deadlineColumns(conf map[string]any) ([]string, []any) {
	var cols []string
	var vals []any
	for _, typ := range DeadlineTypes {
		val := conf[typ+"_deadline"]
		if val == nil {
			continue
		}
		cols = append(cols, typ+"_deadline", typ+"_deadline_label")
		// The deadline value is an object {date, context}; store only the date
		// string (NULL when absent). Passing the raw map to pgx fails to encode.
		vals = append(vals, extractDeadlineDate(val), confStr(conf, typ+"_deadline_label"))
	}
	return cols, vals
}

// extractDeadlineDate pulls the "date" string out of a deadline object, or
// returns nil for a null / malformed value.
func extractDeadlineDate(v any) any {
	switch t := v.(type) {
	case string:
		return t
	case map[string]any:
		if d, ok := t["date"].(string); ok && d != "" {
			return d
		}
		return nil
	default:
		return nil
	}
}

func deadlineSetClause() string {
	parts := []string{}
	for _, typ := range DeadlineTypes {
		parts = append(parts, fmt.Sprintf("%s_deadline = EXCLUDED.%s_deadline", typ, typ))
		parts = append(parts, fmt.Sprintf("%s_deadline_label = COALESCE(EXCLUDED.%s_deadline_label, conferences.%s_deadline_label)", typ, typ, typ))
	}
	return strings.Join(parts, ", ")
}

func deadlinePreviousSetClause() string {
	parts := []string{}
	for _, typ := range DeadlineTypes {
		parts = append(parts, fmt.Sprintf("%s_deadline_previous = COALESCE(conferences.%s_deadline_previous, EXCLUDED.%s_deadline_previous)", typ, typ, typ))
	}
	return strings.Join(parts, ", ")
}
