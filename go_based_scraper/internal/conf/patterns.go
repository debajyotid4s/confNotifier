// Core classification logic: decide whether a URL looks like a CFP.
package conf

import (
	"regexp"
	"strings"
	"time"
)

var staleWordsRe = regexp.MustCompile(
	`(?:^|[-_/.])(?:past|previous|archives?|history|proceedings?|` +
		`report|gallery|photos?|highlights?|recap|concluded|completed)(?:$|[-_/.])`,
)

// ClassifyLink decides whether url looks like a conference/CFP page.
//
// Returns (isCandidate, reason). Reason names the deciding signal.
func ClassifyLink(url string, now time.Time) (bool, string) {
	if url == "" {
		return false, "empty"
	}
	lower := strings.ToLower(url)
	if !strings.HasPrefix(lower, "http://") && !strings.HasPrefix(lower, "https://") {
		return false, "bad_scheme"
	}
	p := parseSimpleURL(url)
	if p == nil {
		return false, "unparseable"
	}
	hostname := strings.ToLower(p.Host)
	if hostname == "" {
		return false, "no_host"
	}
	if IsBlockedHost(hostname) {
		return false, "blocked_host"
	}
	if !IsHTMLURL(url) {
		return false, "non_html"
	}
	pathAndQuery := p.Path
	if p.Query != "" {
		pathAndQuery += "?" + p.Query
	}
	pathAndQuery = strings.ToLower(pathAndQuery)
	if HasJunkSegment(hostname, p.Path) {
		return false, "junk_segment"
	}
	if staleWordsRe.MatchString(pathAndQuery) {
		return false, "stale_wording"
	}
	verdict := YearVerdict(hostname+pathAndQuery, now)
	if verdict == "stale" {
		return false, "stale_year"
	}
	labels := HostLabels(hostname)
	signal := PositiveSignal(labels, pathAndQuery)
	if signal == "" {
		return false, "no_signal"
	}
	if signal == "event_word_path" && verdict != "live" {
		return false, "weak_signal_no_year"
	}
	return true, signal
}
