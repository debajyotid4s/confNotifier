// Seen links types and constants.
package store

import (
	"fmt"
	"strings"
	"time"
)

// SeenLink represents a seen_links row.
type SeenLink struct {
	URL         string
	Source      string
	Status      string
	RetryCount  int
	LastAttempt *time.Time
}

var retryBackoffHours = []int{6, 24, 72}

func sqlTerms(vals []string) string {
	parts := make([]string, len(vals))
	for i, v := range vals {
		parts[i] = fmt.Sprintf("'%s'", v)
	}
	return "(" + strings.Join(parts, ", ") + ")"
}
