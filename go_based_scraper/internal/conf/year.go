// Year window helpers for conference edition detection.
package conf

import (
	"fmt"
	"regexp"
	"time"
)

// Editions this many years back are still allowed.
const YearsBack = 1

// Editions this many years ahead are allowed.
const YearsAhead = 3

var yearRe = regexp.MustCompile(`(?:19|20)\d{2}`)

// YearWindow returns the inclusive [min, max] edition year currently considered live.
func YearWindow(now time.Time) (int, int) {
	y := now.Year()
	return y - YearsBack, y + YearsAhead
}

// YearsIn returns all 4-digit year-like tokens found in text.
func YearsIn(text string) []int {
	matches := yearRe.FindAllString(text, -1)
	result := make([]int, 0, len(matches))
	for _, m := range matches {
		var y int
		if parseYear(m, &y) == nil {
			result = append(result, y)
		}
	}
	return result
}

// YearVerdict classifies the year tokens in text.
// Returns "live", "stale", or "none".
func YearVerdict(text string, now time.Time) string {
	found := YearsIn(text)
	if len(found) == 0 {
		return "none"
	}
	lo, hi := YearWindow(now)
	for _, y := range found {
		if y >= lo && y <= hi {
			return "live"
		}
	}
	// Check if max found year is before the window.
	maxY := found[0]
	for _, y := range found[1:] {
		if y > maxY {
			maxY = y
		}
	}
	if maxY < lo {
		return "stale"
	}
	return "none"
}

func parseYear(s string, out *int) error {
	n, err := fmt.Sscanf(s, "%4d", out)
	if n == 0 {
		return err
	}
	return nil
}
