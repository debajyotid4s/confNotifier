// Extraction normalization: flatten nested deadlines and apply sanitization.
package conf

import (
	"log"
	"time"
)

// NormalizeExtraction flattens nested deadline objects and sanitises every value.
func NormalizeExtraction(raw map[string]any, now time.Time) map[string]any {
	out := make(map[string]any)
	for k, v := range raw {
		out[k] = v
	}
	for _, typ := range DeadlineTypes {
		fieldName := typ + "_deadline"
		deadlineObj, ok := out[fieldName].(map[string]any)
		if ok {
			if d, ok := deadlineObj["date"].(string); ok {
				out[fieldName] = d
			}
			if ctx, ok := deadlineObj["context"].(string); ok {
				out[fieldName+"_context"] = ctx
			}
		} else {
			out[fieldName+"_context"] = nil
		}
		out[fieldName+"_label"] = DeadlineLabels[typ]
	}
	out, notes := SanitizeDates(out, now)
	if len(notes) > 0 {
		for _, note := range notes {
			log.Printf("sanitize: %s", note)
		}
	}
	out["sanitize_notes"] = notes
	SanitizeDescription(out)
	return out
}
