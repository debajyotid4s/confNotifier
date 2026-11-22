// Outcome enum and terminal-status mapping.
package conf

import "fmt"

// Outcome records what happened to one candidate URL.
type Outcome int

const (
	AlreadyDecided Outcome = iota
	DuplicateURL
	DuplicateEdition
	StaleURL
	NotConference
	LowConfidence
	PastConference
	InvalidPermanent
	Saved
	Updated
	FailedExtraction
	FailedSave
	FailedValidation
)

var outcomeNames = map[Outcome]string{
	AlreadyDecided:   "already_decided",
	DuplicateURL:     "duplicate_url",
	DuplicateEdition: "duplicate_edition",
	StaleURL:         "stale_url",
	NotConference:    "not_conference",
	LowConfidence:    "low_confidence",
	PastConference:   "past_conference",
	InvalidPermanent: "invalid_permanent",
	Saved:            "saved",
	Updated:          "updated",
	FailedExtraction: "failed_extraction",
	FailedSave:       "failed_save",
	FailedValidation: "failed_validation",
}

func (o Outcome) String() string {
	if n, ok := outcomeNames[o]; ok {
		return n
	}
	return fmt.Sprintf("outcome_%d", o)
}

// TerminalStatus maps each terminal outcome to a seen_links status.
var TerminalStatus = map[Outcome]*string{
	AlreadyDecided:   nil,
	DuplicateURL:     strPtr("extracted"),
	DuplicateEdition: strPtr("extracted"),
	StaleURL:         strPtr("not_conference"),
	NotConference:    strPtr("not_conference"),
	LowConfidence:    strPtr("low_confidence"),
	PastConference:   strPtr("not_conference"),
	InvalidPermanent: strPtr("low_confidence"),
	Saved:            strPtr("extracted"),
	Updated:          strPtr("extracted"),
	FailedExtraction: strPtr("failed_transient"),
	FailedSave:       nil,
	FailedValidation: strPtr("failed_transient"),
}

// SkippedOutcomes are outcomes that skip further processing.
var SkippedOutcomes = map[Outcome]struct{}{
	AlreadyDecided: {}, DuplicateURL: {}, DuplicateEdition: {},
	StaleURL: {}, NotConference: {}, LowConfidence: {},
	PastConference: {}, InvalidPermanent: {}, Updated: {},
}

func strPtr(s string) *string { return &s }
