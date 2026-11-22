// Deadline and submission type constants.
package conf

// DeadlineTypes are the only deadline kinds tracked.
var DeadlineTypes = []string{"abstract", "full_paper"}

// SubmissionTypes is an alias for DeadlineTypes.
var SubmissionTypes = []string{"abstract", "full_paper"}

// DeadlineLabels maps type to human-readable label.
var DeadlineLabels = map[string]string{
	"abstract":   "Abstract Submission",
	"full_paper": "Full Paper Submission",
}

// MaxDescriptionWords is the maximum words allowed in a conference description.
const MaxDescriptionWords = 200

// DeadlineDBFields lists all database columns for deadlines.
var DeadlineDBFields []string

func init() {
	for _, typ := range DeadlineTypes {
		DeadlineDBFields = append(DeadlineDBFields, typ+"_deadline",
			typ+"_deadline_label", typ+"_deadline_previous")
	}
}

// DeadlineField returns the DB column name for a deadline type and suffix.
func DeadlineField(typ, suffix string) string {
	return typ + "_deadline" + suffix
}
