// Internal date parsing helpers: coercion and regex.
package conf

import (
	"regexp"
	"strings"
	"time"
)

var nonDates = map[string]struct{}{
	"": {}, "tba": {}, "tbd": {}, "n/a": {}, "na": {}, "none": {},
	"null": {}, "unknown": {}, "to be announced": {}, "to be decided": {},
	"not announced": {}, "coming soon": {},
}

var months = map[string]int{
	"jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
	"apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
	"aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
	"oct": 10, "october": 10, "nov": 11, "november": 11,
	"dec": 12, "december": 12,
}

var isoDateRe = regexp.MustCompile(`\b(\d{4})-(\d{1,2})-(\d{1,2})\b`)
var slashDateRe = regexp.MustCompile(`\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b`)
var textDateRe = regexp.MustCompile(
	`(?:(?P<m1>[a-z]+)\.?\s+(?P<d1>\d{1,2})|(?P<d2>\d{1,2})\s+(?P<m2>[a-z]+)\.?)` +
		`[,\s]+(?P<y>(?:19|20)\d{2})`,
)

func coerceString(text string) time.Time {
	text = strings.TrimSpace(text)
	lower := strings.ToLower(text)
	for nd := range nonDates {
		if lower == nd {
			return time.Time{}
		}
	}
	if m := isoDateRe.FindStringSubmatch(text); m != nil {
		return buildDate(m[1], m[2], m[3])
	}
	if m := slashDateRe.FindStringSubmatch(text); m != nil {
		if d := buildSlashDate(m); !d.IsZero() {
			return d
		}
	}
	if m := textDateRe.FindStringSubmatch(text); m != nil {
		return buildTextDate(m)
	}
	return time.Time{}
}
