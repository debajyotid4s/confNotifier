// URL canonicalisation: path normalization helpers.
package conf

import "regexp"

var indexFiles = regexp.MustCompile(`(?:/index|/default|/home|/main)\.(?:html?|php|asp|aspx|jsp|cgi)$`)

var redundantTail = regexp.MustCompile(
	`/(?:home|index|main|default|welcome|en|en-us|en_us|bn)$`,
)
