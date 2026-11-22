// Internal date building helpers.
package conf

import (
	"strconv"
	"time"
)

func buildDate(year, month, day string) time.Time {
	y, _ := strconv.Atoi(year)
	m, _ := strconv.Atoi(month)
	d, _ := strconv.Atoi(day)
	return makeDate(y, m, d)
}

func buildSlashDate(m []string) time.Time {
	d1, _ := strconv.Atoi(m[1])
	m1, _ := strconv.Atoi(m[2])
	y, _ := strconv.Atoi(m[3])
	if d := makeDate(y, m1, d1); !d.IsZero() {
		return d
	}
	return makeDate(y, d1, m1)
}

func buildTextDate(m []string) time.Time {
	var month int
	if m[1] != "" {
		month = months[lower(m[1])]
	} else {
		month = months[lower(m[4])]
	}
	if month == 0 {
		return time.Time{}
	}
	d, _ := strconv.Atoi(m[2])
	if m[2] == "" {
		d, _ = strconv.Atoi(m[3])
	}
	y, _ := strconv.Atoi(m[5])
	return makeDate(y, month, d)
}

func makeDate(year, month, day int) time.Time {
	if month < 1 || month > 12 || day < 1 || day > 31 {
		return time.Time{}
	}
	t := time.Date(year, time.Month(month), day, 0, 0, 0, 0, time.UTC)
	if t.Year() != year || int(t.Month()) != month || t.Day() != day {
		return time.Time{}
	}
	return t
}

func lower(s string) string {
	r := []rune(s)
	for i, c := range r {
		if c >= 'A' && c <= 'Z' {
			r[i] = c + 32
		}
	}
	return string(r)
}
