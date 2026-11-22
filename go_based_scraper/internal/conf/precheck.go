// Pre-check predicates: conference in the past, deadline extraction.
package conf

import (
	"time"
)

// IsConferenceInPast returns true when the conference dates have already passed.
func IsConferenceInPast(conf map[string]any, now time.Time) bool {
	if now.IsZero() {
		now = time.Now().UTC()
	}
	ds, ok := conf["date_start"]
	de, ok2 := conf["date_end"]
	if ok || ok2 {
		if ds, ok := ds.(string); ok {
			if CoerceDate(ds).Before(now) {
				if de, ok := de.(string); ok {
					if CoerceDate(de).Before(now) {
						return true
					}
					if CoerceDate(de).IsZero() {
						return true
					}
				}
			}
		}
	}
	return false
}

// HasUsableContent returns true when an extraction carries at least one
// fact worth storing: start/end dates or at least one deadline.
func HasUsableContent(conf map[string]any) bool {
	if _, ok := conf["date_start"]; ok {
		return true
	}
	if _, ok := conf["date_end"]; ok {
		return true
	}
	for _, typ := range SubmissionTypes {
		if _, ok := conf[typ+"_deadline"]; ok {
			return true
		}
	}
	return false
}

// ExtractedDeadlines returns the deadline types that have non-empty values.
func ExtractedDeadlines(conf map[string]any) []string {
	var types []string
	for _, typ := range SubmissionTypes {
		if _, ok := conf[typ+"_deadline"]; ok {
			types = append(types, typ)
		}
	}
	return types
}
