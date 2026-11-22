// Positive signal detection for conference classification.
package conf

import (
	"regexp"
	"strings"
)

// PositiveSignal returns the name of the first positive conference signal found,
// or nil when no signal is present.
func PositiveSignal(labels []string, pathAndQuery string) string {
	for _, label := range labels {
		if LabelLooksLikeConference(label) {
			return "host_label"
		}
	}
	joined := strings.Join(labels, "")
	for _, acr := range KnownAcronyms {
		if strings.Contains(joined, acr) {
			return "known_acronym"
		}
	}
	if cfpRe.MatchString(pathAndQuery) {
		return "cfp_wording"
	}
	if eventYearRe.MatchString(pathAndQuery) {
		return "event_year_path"
	}
	for _, acr := range KnownAcronyms {
		if strings.Contains(pathAndQuery, acr) {
			return "known_acronym_path"
		}
	}
	for _, match := range acronymYearRe.FindAllStringSubmatch(pathAndQuery, -1) {
		word := match[1]
		if containsString(NonEventWords, word) {
			continue
		}
		if containsString(LookalikeWords, word) {
			continue
		}
		if containsString(JunkSegments, word) {
			continue
		}
		return "acronym_year_path"
	}
	for _, word := range EventWords {
		pattern := `(?:^|[-_/])` + regexp.QuoteMeta(word) + `(?:$|[-_/s])`
		if regexp.MustCompile(pattern).MatchString(pathAndQuery) {
			return "event_word_path"
		}
	}
	return ""
}
