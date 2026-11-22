// Deadline context validation keywords.
package conf

// FieldKeywords maps deadline type to words that identify it.
var FieldKeywords = map[string][]string{
	"abstract":   {"abstract", "extended abstract", "short paper", "summary", "proposal submission"},
	"full_paper": {"full paper", "final paper", "manuscript", "full-length", "complete paper", "paper submission"},
}

// PostSubmissionKeywords are deadline kinds we do not track.
var PostSubmissionKeywords = []string{
	"notification of acceptance", "acceptance notification", "notification date",
	"acceptance letter", "author notification", "review result",
	"camera ready", "camera-ready", "final version", "final manuscript due",
	"registration deadline", "early bird", "late registration",
	"registration closes", "payment deadline",
}
