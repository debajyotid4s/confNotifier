// ValidateExtraction runs every check against one extraction.
package conf

import (
	"fmt"
	"sort"
	"strings"
	"time"
)

// ValidateExtraction runs every check against one extraction and returns a verdict.
func ValidateExtraction(conf map[string]any, storedDeadlines map[string]any, now time.Time) Verdict {
	mismatches := contextMismatchDetails(conf)
	if len(mismatches) > 0 {
		var parts []string
		for t, a := range mismatches {
			parts = append(parts, fmt.Sprintf("%s→%s", t, a))
		}
		sort.Strings(parts)
		return Reject(fmt.Sprintf("context mismatch (%s)", strings.Join(parts, ", ")),
			mapKeys(mismatches), true)
	}
	if allDeadlinesPast(conf, now) {
		return Reject("all extracted deadlines are in the past", nil, true)
	}
	if storedDeadlines != nil {
		newVals := make(map[string]time.Time)
		storedVals := make(map[string]time.Time)
		for _, t := range SubmissionTypes {
			newVals[t] = CoerceDate(conf[t+"_deadline"])
			storedVals[t] = CoerceDate(storedDeadlines[t])
		}
		if hasAny(newVals) && hasAny(storedVals) {
			if swapped := checkDeadlineSwap(newVals, storedVals); len(swapped) > 0 {
				return Reject(fmt.Sprintf("deadline swap detected for %v", swapped), swapped, false)
			}
		}
	}
	return Valid()
}

func checkDeadlineSwap(newVals, storedVals map[string]time.Time) []string {
	var swapped []string
	for i, t1 := range SubmissionTypes {
		n1, ok1 := newVals[t1]
		if !ok1 || n1.IsZero() {
			continue
		}
		for _, t2 := range SubmissionTypes[i+1:] {
			n2, ok2 := newVals[t2]
			if !ok2 || n2.IsZero() || n1 == n2 {
				continue
			}
			if n1 == storedVals[t2] && n2 == storedVals[t1] {
				swapped = append(swapped, t1, t2)
			}
		}
	}
	return swapped
}
