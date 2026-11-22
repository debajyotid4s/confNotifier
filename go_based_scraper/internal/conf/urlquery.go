// URL canonicalisation: query string cleaning.
package conf

import "strings"

var junkQueryPrefixes = []string{"utm_", "fbclid", "gclid", "msclkid", "ref", "phpsessid", "sessionid"}

func cleanQuery(query string) string {
	if query == "" {
		return ""
	}
	var kept []string
	for _, part := range strings.Split(query, "&") {
		if part == "" {
			continue
		}
		key := strings.SplitN(part, "=", 2)[0]
		key = strings.ToLower(key)
		skip := false
		for _, prefix := range junkQueryPrefixes {
			if strings.HasPrefix(key, prefix) {
				skip = true
				break
			}
		}
		if !skip {
			kept = append(kept, part)
		}
	}
	if len(kept) == 0 {
		return ""
	}
	return "?" + sortedJoin(kept)
}

func sortedJoin(items []string) string {
	for i := 1; i < len(items); i++ {
		for j := i; j > 0 && items[j] < items[j-1]; j-- {
			items[j], items[j-1] = items[j-1], items[j]
		}
	}
	return strings.Join(items, "&")
}
