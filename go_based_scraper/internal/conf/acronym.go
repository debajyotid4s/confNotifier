// Title normalisation: acronym extraction.
package conf

import (
	"regexp"
	"strings"
)

var acronymRe = regexp.MustCompile(`\b([A-Z][A-Z0-9]{2,15})\b`)
var yearInTitleRe = regexp.MustCompile(`(?:19|20)\d{2}`)
var parenRe = regexp.MustCompile(`\(([^)]*)\)`)

// AcronymFromTitle pulls the conference acronym out of a title.
//
// Prefers a parenthesised acronym ("... (ICCIT 2027)"), then any all-caps
// token that is not a known non-acronym word.
func AcronymFromTitle(title string) string {
	if title == "" {
		return ""
	}
	for _, paren := range parenRe.FindAllString(title, -1) {
		paren = strings.Trim(paren, " ()")
		for _, token := range acronymRe.FindAllString(paren, -1) {
			cleaned := yearInTitleRe.ReplaceAllString(token, "")
			if len(cleaned) >= 3 && !containsString(TitleStopwords, strings.ToLower(cleaned)) {
				return cleaned
			}
		}
	}
	for _, token := range acronymRe.FindAllString(title, -1) {
		cleaned := yearInTitleRe.ReplaceAllString(token, "")
		if len(cleaned) >= 3 && !containsString(TitleStopwords, strings.ToLower(cleaned)) {
			return cleaned
		}
	}
	return ""
}
