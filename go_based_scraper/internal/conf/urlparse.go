// URL canonicalisation: parsing and URL struct.
package conf

import "strings"

// simpleURL is a minimal parsed URL representation.
type simpleURL struct {
	Host  string
	Path  string
	Query string
}

func parseSimpleURL(raw string) *simpleURL {
	scheme, after, ok := strings.Cut(raw, "://")
	if !ok || scheme == "" || (scheme != "http" && scheme != "https") {
		return nil
	}
	hostEnd := len(after)
	for i, c := range after {
		if c == '/' || c == '?' || c == '#' {
			hostEnd = i
			break
		}
	}
	host := after[:hostEnd]
	rest := after[hostEnd:]
	if rest == "" {
		return &simpleURL{Host: host, Path: "/"}
	}
	if idx := strings.IndexByte(rest, '#'); idx != -1 {
		rest = rest[:idx]
	}
	path, query, _ := strings.Cut(rest, "?")
	return &simpleURL{Host: host, Path: path, Query: query}
}
