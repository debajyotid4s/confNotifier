// URL hygiene helpers.
package conf

import (
	"regexp"
	"strings"
)

var junkRe = regexp.MustCompile(`[/.]+`)

// HasJunkSegment returns true when hostname or path contains a junk segment.
func HasJunkSegment(hostname, path string) bool {
	combined := strings.ToLower(hostname + path)
	segments := junkRe.Split(combined, -1)
	for _, s := range segments {
		if containsString(JunkSegments, s) {
			return true
		}
	}
	return false
}

// IsHTMLURL returns false for URLs pointing at a binary/asset instead of a page.
func IsHTMLURL(url string) bool {
	lower := strings.ToLower(url)
	for _, ext := range NonHTMLExtensions {
		if strings.HasSuffix(lower, ext) {
			return false
		}
	}
	return true
}

// IsBlockedHost returns true for social networks, publishers, and other
// hosts that never host a Bangladeshi CFP.
func IsBlockedHost(hostname string) bool {
	host := strings.ToLower(strings.Trim(hostname, "."))
	host = strings.TrimPrefix(host, "www.")
	for _, b := range HostBlocklist {
		if b == host {
			return true
		}
		if strings.HasSuffix(host, "."+b) {
			return true
		}
	}
	return false
}
