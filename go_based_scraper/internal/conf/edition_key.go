// Edition identity: stable edition key.
package conf

import (
	"strconv"
	"time"
)

// EditionKey returns a stable identity for one edition of one conference,
// or "" if unknowable.
//
// Two records sharing an edition_key are the same conference edition even when
// their URLs differ. "" means "cannot decide" — fall back to URL comparison.
func EditionKey(title string, dateStart time.Time, website string, deadlines []time.Time) string {
	key := TitleKey(title)
	if key == "" {
		return ""
	}
	year := EditionYear(title, website, dateStart, deadlines)
	if year == 0 {
		return ""
	}
	return key + ":" + strconv.Itoa(year)
}
