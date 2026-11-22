// Date coercion and plausibility checks.
package conf

import (
	"fmt"
	"time"
)

// CoerceDate parses a model-supplied date into a Go time.Time, or returns zero.
//
// Accepts ISO strings, written forms ("August 15, 2027"), slash dates ("15/8/2027"),
// and date/time objects. Returns zero for placeholders ("TBA"), impossible dates,
// and anything unrecognised — never panics.
func CoerceDate(value any) time.Time {
	if value == nil {
		return time.Time{}
	}
	switch v := value.(type) {
	case time.Time:
		return v
	case string:
		return coerceString(v)
	case fmt.Stringer:
		return coerceString(v.String())
	default:
		return time.Time{}
	}
}
