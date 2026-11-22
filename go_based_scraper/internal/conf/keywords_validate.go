// Deadline context validation logic.
package conf

// ValidateDeadlineContext checks if page text matches the expected deadline type.
//
// Returns (isValid, mismatchedField). mismatchedField names the field the text
// actually describes, or "post_submission" for untracked deadline kinds.
func ValidateDeadlineContext(typ, context string) (bool, string) {
	if context == "" {
		return true, ""
	}
	lower := toLower(context)
	for _, kw := range FieldKeywords[typ] {
		if containsStr(lower, kw) {
			return true, ""
		}
	}
	for otherTyp, kws := range FieldKeywords {
		if otherTyp == typ {
			continue
		}
		for _, kw := range kws {
			if containsStr(lower, kw) {
				return false, otherTyp
			}
		}
	}
	for _, kw := range PostSubmissionKeywords {
		if containsStr(lower, kw) {
			return false, "post_submission"
		}
	}
	return true, ""
}

func toLower(s string) string {
	r := []rune(s)
	for i, c := range r {
		if c >= 'A' && c <= 'Z' {
			r[i] = c + 32
		}
	}
	return string(r)
}

func containsStr(s, sub string) bool {
	return len(s) >= len(sub) && indexStr(s, sub) >= 0
}

func indexStr(s, sub string) int {
	for i := 0; i <= len(s)-len(sub); i++ {
		match := true
		for j := 0; j < len(sub); j++ {
			sc, uc := rune(s[i+j]), rune(sub[j])
			if sc >= 'A' && sc <= 'Z' {
				sc += 32
			}
			if sc != uc {
				match = false
				break
			}
		}
		if match {
			return i
		}
	}
	return -1
}
