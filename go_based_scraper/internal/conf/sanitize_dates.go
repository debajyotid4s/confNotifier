// Date sanitization: clamp deadlines to today, drop far-future dates.
package conf

import "time"

// SanitizeDates clamps deadlines to today (never in the future) and
// drops abstract/full_paper deadlines that are more than 14 days in the future.
func SanitizeDates(raw map[string]any, now time.Time) (map[string]any, []string) {
	notes := []string{}
	if now.IsZero() {
		now = time.Now().UTC()
	}
	for _, typ := range DeadlineTypes {
		key := typ + "_deadline"
		val, ok := raw[key]
		if !ok {
			continue
		}
		str, isStr := val.(string)
		if !isStr {
			continue
		}
		parsed := CoerceDate(str)
		if parsed.IsZero() {
			notes = append(notes, typ+"_deadline: unparseable date '"+str+"'")
			raw[key] = nil
			continue
		}
		if parsed.After(now) {
			days := int(time.Until(now).Hours() / 24)
			if -days > 14 {
				notes = append(notes, typ+"_deadline: dropped (more than 14 days in future)")
				raw[key] = nil
			} else {
				notes = append(notes, typ+"_deadline: clamped to today")
				raw[key] = now.Format("2006-01-02")
			}
		}
	}
	return raw, notes
}
