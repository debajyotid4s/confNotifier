// Text sanitization: description word-count truncation.
package conf

import (
	"log"
)

// SanitizeDescription clamps the description to MaxDescriptionWords.
func SanitizeDescription(raw map[string]any) {
	desc, _ := raw["description"].(string)
	if desc != "" {
		words := splitWords(desc)
		if len(words) > MaxDescriptionWords {
			log.Printf("overview_wordcount_violation: %d words (max %d), truncating",
				len(words), MaxDescriptionWords)
			raw["description"] = joinWords(words[:MaxDescriptionWords])
		}
	} else if _, ok := raw["description"]; ok {
		raw["description"] = nil
	}
}

func splitWords(s string) []string {
	var words []string
	var cur []rune
	for _, r := range s {
		if r == ' ' || r == '\t' || r == '\n' || r == '\r' {
			if len(cur) > 0 {
				words = append(words, string(cur))
				cur = nil
			}
		} else {
			cur = append(cur, r)
		}
	}
	if len(cur) > 0 {
		words = append(words, string(cur))
	}
	return words
}

func joinWords(words []string) string {
	if len(words) == 0 {
		return ""
	}
	s := words[0]
	for i := 1; i < len(words); i++ {
		s += " " + words[i]
	}
	return s
}
