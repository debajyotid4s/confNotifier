// URL canonicalisation: folding URLs to stable identity keys.
package conf

import "strings"

// CanonicalURL folds a URL onto a stable identity key.
//
// It forces https, lowercases the host, drops www. and default ports,
// removes fragments and tracking query parameters, strips index.html-style
// filenames and redundant /home tails, and collapses duplicate slashes.
//
// Returns the input unchanged when it cannot be parsed.
func CanonicalURL(raw string) string {
	if raw == "" {
		return ""
	}
	raw = strings.TrimSpace(raw)
	p := parseSimpleURL(raw)
	if p == nil {
		return raw
	}
	hostname := strings.ToLower(p.Host)
	if hostname == "" {
		return raw
	}
	hostname = strings.TrimPrefix(hostname, "www.")
	path := strings.ReplaceAll(p.Path, "//", "/")
	path = indexFiles.ReplaceAllString(path, "")
	path = strings.TrimRight(path, "/")
	for i := 0; i < 3; i++ {
		stripped := redundantTail.ReplaceAllString(path, "")
		if stripped == path {
			break
		}
		path = stripped
	}
	return "https://" + hostname + path + cleanQuery(p.Query)
}

// SameURL returns true when two URLs denote the same page after canonicalisation.
func SameURL(a, b string) bool {
	return a != "" && b != "" && CanonicalURL(a) == CanonicalURL(b)
}
