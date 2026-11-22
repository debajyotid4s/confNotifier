// Edition identity: year determination.
package conf

import (
	"fmt"
	"sort"
	"time"
)

// EditionYear returns the best guess of which edition (year) a conference
// record refers to.
//
// Priority: explicit conference start date > earliest submission deadline >
// year in the title > year in the URL. Returns 0 when nothing is known.
func EditionYear(title, website string, dateStart time.Time, deadlines []time.Time) int {
	if !dateStart.IsZero() {
		return dateStart.Year()
	}
	sorted := make([]time.Time, 0, len(deadlines))
	for _, d := range deadlines {
		if !d.IsZero() {
			sorted = append(sorted, d)
		}
	}
	sort.Slice(sorted, func(i, j int) bool {
		return sorted[i].Before(sorted[j])
	})
	for _, d := range sorted {
		if y := yearFromValue(d); y != 0 {
			return y
		}
	}
	for _, source := range []string{title, website} {
		if found := YearsIn(source); len(found) > 0 {
			m := found[0]
			for _, y := range found[1:] {
				if y > m {
					m = y
				}
			}
			return m
		}
	}
	return 0
}

func yearFromValue(v any) int {
	switch t := v.(type) {
	case time.Time:
		if !t.IsZero() {
			return t.Year()
		}
	case string:
		if len(t) >= 4 {
			var y int
			_, err := fmt.Sscanf(t[:4], "%4d", &y)
			if err == nil && y >= 1900 && y <= 2200 {
				return y
			}
		}
	}
	return 0
}
