// Validation predicates: context mismatch, deadline age, map helpers.
package conf

import "time"

func contextMismatchDetails(conf map[string]any) map[string]string {
	details := map[string]string{}
	for _, typ := range SubmissionTypes {
		ctx, _ := conf[typ+"_deadline_context"].(string)
		if ctx == "" {
			continue
		}
		valid, mismatch := ValidateDeadlineContext(typ, ctx)
		if !valid {
			details[typ] = mismatch
		}
	}
	return details
}

func allDeadlinesPast(conf map[string]any, now time.Time) bool {
	var deadlines []time.Time
	for _, typ := range SubmissionTypes {
		if d := CoerceDate(conf[typ+"_deadline"]); !d.IsZero() {
			deadlines = append(deadlines, d)
		}
	}
	return len(deadlines) > 0 && allBefore(deadlines, now)
}

func allBefore(ds []time.Time, cutoff time.Time) bool {
	for _, d := range ds {
		if !d.Before(cutoff) {
			return false
		}
	}
	return true
}

func hasAny(m map[string]time.Time) bool {
	for _, t := range m {
		if !t.IsZero() {
			return true
		}
	}
	return false
}

func mapKeys(m map[string]string) []string {
	var k []string
	for key := range m {
		k = append(k, key)
	}
	return k
}
