// Tests for year window helpers.
package conf

import (
	"testing"
	"time"
)

var testNow = time.Date(2026, 6, 15, 0, 0, 0, 0, time.UTC)

func TestYearWindow(t *testing.T) {
	lo, hi := YearWindow(testNow)
	if lo != 2025 || hi != 2029 {
		t.Errorf("YearWindow = (%d, %d), want (2025, 2029)", lo, hi)
	}
}

func TestYearsIn(t *testing.T) {
	got := YearsIn("icap2025.sust.edu/2027/")
	want := []int{2025, 2027}
	if len(got) != len(want) || got[0] != want[0] || got[1] != want[1] {
		t.Errorf("YearsIn = %v, want %v", got, want)
	}
	if got = YearsIn(""); len(got) != 0 {
		t.Errorf("YearsIn(\"\") = %v, want []", got)
	}
}
