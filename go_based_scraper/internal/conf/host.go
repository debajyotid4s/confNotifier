// Hostname label helpers.
package conf

import (
	"regexp"
	"strings"
)

// HostLabels returns hostname labels with the public suffix and 'www' removed.
//
// "icerie2027.sust.edu" -> ["icerie2027", "sust"]
func HostLabels(hostname string) []string {
	host := strings.ToLower(strings.Trim(hostname, "."))
	host = strings.TrimPrefix(host, "www.")
	parts := strings.Split(host, ".")
	var cleaned []string
	for _, p := range parts {
		if p != "" {
			cleaned = append(cleaned, p)
		}
	}
	tail := map[string]struct{}{
		"ac": {}, "edu": {}, "org": {}, "com": {}, "net": {},
		"gov": {}, "info": {}, "bd": {}, "io": {}, "co": {},
	}
	for len(cleaned) > 1 {
		last := cleaned[len(cleaned)-1]
		if _, ok := tail[last]; ok {
			cleaned = cleaned[:len(cleaned)-1]
		} else {
			break
		}
	}
	return cleaned
}

// LabelLooksLikeConference returns true when a host label matches an
// acronym shape and is not a known lookalike word.
func LabelLooksLikeConference(label string) bool {
	bare := yearSuffixRe.ReplaceAllString(label, "")
	if containsString(LookalikeWords, bare) {
		return false
	}
	if containsString(LookalikeWords, label) {
		return false
	}
	for _, shape := range hostLabelShapes {
		if shape.MatchString(label) {
			return true
		}
	}
	return false
}

var yearSuffixRe = regexp.MustCompile(`[-_.]?(?:19|20)\d{2}$`)
