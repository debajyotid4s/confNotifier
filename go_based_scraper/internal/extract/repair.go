package extract

import (
	"encoding/json"
	"regexp"
	"strings"
)

var trailingCommaRe = regexp.MustCompile(`,(\s*[}\]])`)

// RepairJSON best-effort parses a model reply that is not quite valid JSON.
// It is the Go port of scraper/extraction/json_repair/repair.py.
//
// It tries, in order: the raw string, the fence-stripped string, the innermost
// {...} span, each candidate with trailing commas removed, and the truncated
// tail re-balanced. The first that unmarshals into a JSON object wins.
func RepairJSON(raw string) (map[string]any, error) {
	if strings.TrimSpace(raw) == "" {
		return nil, errEmpty
	}
	var candidates []string
	add := func(v string) {
		if v != "" && strings.TrimSpace(v) != "" && !containsStr(candidates, strings.TrimSpace(v)) {
			candidates = append(candidates, strings.TrimSpace(v))
		}
	}
	add(raw)
	stripped := stripFences(raw)
	add(stripped)
	start, end := strings.Index(stripped, "{"), strings.LastIndex(stripped, "}")
	if start >= 0 && end > start {
		add(stripped[start : end+1])
	}
	for _, base := range candidates {
		add(trailingCommaRe.ReplaceAllString(base, "$1"))
	}
	if start >= 0 {
		add(closeTruncated(stripped[start:]))
	}
	for _, c := range candidates {
		var parsed map[string]any
		if err := json.Unmarshal([]byte(c), &parsed); err == nil {
			return parsed, nil
		}
	}
	return nil, errUnparseable
}

var errEmpty = &repairError{"empty reply"}
var errUnparseable = &repairError{"reply was not valid JSON"}

type repairError struct{ msg string }

func (e *repairError) Error() string { return e.msg }

func stripFences(text string) string {
	s := strings.TrimSpace(text)
	// Strip a leading ```json / ``` and a trailing ``` (either side).
	s = replaceFirst(`^\s*`+"```"+`(?:json)?\s*`, "", s)
	s = replaceFirst(`\s*`+"```"+`\s*$`, "", s)
	return strings.TrimSpace(s)
}

// replaceFirst applies a single regexp substitution (anchored helpers below).
func replaceFirst(pattern, repl, s string) string {
	re := regexp.MustCompile(pattern)
	return re.ReplaceAllString(s, repl)
}

func containsStr(haystack []string, needle string) bool {
	for _, h := range haystack {
		if h == needle {
			return true
		}
	}
	return false
}

// safeTrunc returns at most n bytes of s, never panicking on short input.
func safeTrunc(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n]
}

// closeTruncated re-balances an object truncated mid-write by the token limit.
// Ported from scraper/extraction/json_repair/truncate.py.
func closeTruncated(text string) string {
	var stack []rune
	inString := false
	escaped := false
	cutAt := -1
	var cutStack []rune

	for i, ch := range text {
		if escaped {
			escaped = false
			continue
		}
		if ch == '\\' {
			escaped = true
			continue
		}
		if ch == '"' {
			inString = !inString
			continue
		}
		if inString {
			continue
		}
		switch ch {
		case '{', '[':
			if ch == '{' {
				stack = append(stack, '}')
			} else {
				stack = append(stack, ']')
			}
		case '}', ']':
			if len(stack) > 0 {
				stack = stack[:len(stack)-1]
			}
			if len(stack) == 0 {
				return text[:i+1]
			}
			cutAt, cutStack = i+1, append([]rune(nil), stack...)
		case ',':
			if len(stack) == 1 {
				cutAt, cutStack = i, append([]rune(nil), stack...)
			}
		}
	}
	if cutAt < 0 {
		return ""
	}
	body := strings.TrimRight(text[:cutAt], " \t\r\n")
	body = strings.TrimSuffix(body, ",")
	if body == "" {
		return ""
	}
	reversed := make([]rune, len(cutStack))
	for i := 0; i < len(cutStack); i++ {
		reversed[i] = cutStack[len(cutStack)-1-i]
	}
	return body + string(reversed)
}
