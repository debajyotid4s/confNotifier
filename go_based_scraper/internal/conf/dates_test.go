// Tests for date coercion.
package conf

import (
	"testing"
	"time"
)

func TestCoerceDate(t *testing.T) {
	tests := []struct {
		input any
		want  time.Time
	}{
		{nil, time.Time{}},
		{"2026-08-15", time.Date(2026, 8, 15, 0, 0, 0, 0, time.UTC)},
		{"tba", time.Time{}},
		{"tbd", time.Time{}},
		{"n/a", time.Time{}},
		{"na", time.Time{}},
		{"none", time.Time{}},
		{"null", time.Time{}},
		{"unknown", time.Time{}},
		{"to be announced", time.Time{}},
		{"to be decided", time.Time{}},
		{"not announced", time.Time{}},
		{"coming soon", time.Time{}},
		{"august 15, 2026", time.Date(2026, 8, 15, 0, 0, 0, 0, time.UTC)},
		{"15 august 2026", time.Date(2026, 8, 15, 0, 0, 0, 0, time.UTC)},
		{"15/8/2026", time.Date(2026, 8, 15, 0, 0, 0, 0, time.UTC)},
		{"8/15/2026", time.Date(2026, 8, 15, 0, 0, 0, 0, time.UTC)},
		{"not-a-date", time.Time{}},
		{"", time.Time{}},
		{time.Date(2026, 8, 15, 0, 0, 0, 0, time.UTC), time.Date(2026, 8, 15, 0, 0, 0, 0, time.UTC)},
		{"2027-02-30", time.Time{}},
	}
	for _, tt := range tests {
		got := CoerceDate(tt.input)
		if got != tt.want {
			t.Errorf("CoerceDate(%v) = %v, want %v", tt.input, got, tt.want)
		}
	}
}
