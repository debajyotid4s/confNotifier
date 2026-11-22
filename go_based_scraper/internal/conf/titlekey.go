// Title normalisation: title key generation.
package conf

import (
	"regexp"
	"strings"
)

var romanRe = regexp.MustCompile(`^[ivxlcdm]+$`)
var ordinalRe = regexp.MustCompile(`\b\d+\s*(?:st|nd|rd|th)\b`)
var nonAlphaRe = regexp.MustCompile(`[^a-zA-Z\s]`)

// TitleKey normalises a title to a comparable identity key.
//
// "3rd International Conference on Computing (ICCIT 2027)" -> "iccit"
// "International Conference on Computing and Information Technology" ->
//
//	"computinginformationtechnology"
func TitleKey(title string) string {
	if title == "" {
		return ""
	}
	acronym := AcronymFromTitle(title)
	if acronym != "" {
		return strings.ToLower(acronym)
	}
	text := yearInTitleRe.ReplaceAllString(title, " ")
	text = ordinalRe.ReplaceAllString(text, " ")
	text = nonAlphaRe.ReplaceAllString(text, " ")
	words := strings.Fields(text)
	var significant []string
	for _, w := range words {
		lower := strings.ToLower(w)
		if containsString(TitleStopwords, lower) {
			continue
		}
		if romanRe.MatchString(lower) || len(lower) <= 2 {
			continue
		}
		significant = append(significant, lower)
	}
	result := strings.Join(significant, "")
	if len(result) > 64 {
		return result[:64]
	}
	return result
}
