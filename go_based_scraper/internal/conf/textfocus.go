// FocusText compresses page text down to budget characters.
package conf

import "strings"

// FocusText compresses page text down to budget characters, keeping deadline mentions.
func FocusText(text string, budget int, head int) string {
	if text == "" {
		return ""
	}
	if len(text) <= budget {
		return text
	}
	if head <= 0 {
		head = headChars
	}
	if budget <= 0 {
		budget = defaultBudget
	}
	h := text[:min(head, budget)]
	remaining := budget - len(h)
	if remaining <= 0 {
		return h
	}
	spans := interestingSpans(text)
	var tailSpans [][2]int
	for _, s := range spans {
		if s[1] > head {
			tailSpans = append(tailSpans, [2]int{s[0], s[1]})
		}
	}
	if len(tailSpans) == 0 {
		return text[:budget]
	}
	var chosen [][2]int
	used := 0
	for _, span := range tailSpans {
		start := max(span[0], head)
		length := span[1] - start
		if length <= 0 || used+length > remaining {
			continue
		}
		chosen = append(chosen, [2]int{start, span[1]})
		used += length
	}
	if len(chosen) == 0 {
		return text[:budget]
	}
	sortSpans(chosen)
	var parts []string
	parts = append(parts, h)
	prevEnd := head
	for _, span := range chosen {
		if span[0] > prevEnd {
			parts = append(parts, "\n[...]\n")
		}
		parts = append(parts, text[span[0]:span[1]])
		prevEnd = span[1]
	}
	result := strings.Join(parts, "")
	if len(result) > budget {
		return result[:budget]
	}
	return result
}
