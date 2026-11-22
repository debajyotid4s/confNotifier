// Package pipeline orchestrates one scraper run: discover candidates, extract
// each with the LLM, validate, persist, and notify. It is the Go port of
// scraper/pipeline.
package pipeline

// Outcome is what happened to one candidate URL (scraper/pipeline/outcomes.py).
type Outcome int

const (
	// AlreadyDecided: URL already terminal in seen_links.
	AlreadyDecided Outcome = iota
	// DuplicateURL: this URL is already a saved conference.
	DuplicateURL
	// DuplicateEdition: same edition under a different URL — merged.
	DuplicateEdition
	// StaleURL: hostname/path advertises a past edition.
	StaleURL
	// NotConference: the model said no.
	NotConference
	// LowConfidence: below the confidence floor.
	LowConfidence
	// PastConference: the event already happened.
	PastConference
	// InvalidPermanent: the page contradicts itself — do not retry.
	InvalidPermanent
	// Saved: a new conference was stored.
	Saved
	// Updated: an existing conference was refreshed.
	Updated
	// FailedExtraction: fetch/LLM failure — retry with backoff.
	FailedExtraction
	// FailedSave: DB write failure — retry.
	FailedSave
	// FailedValidation: swap/context suspected — retry.
	FailedValidation
)

// String renders the outcome name (matches the Python enum member names).
func (o Outcome) String() string {
	switch o {
	case AlreadyDecided:
		return "ALREADY_DECIDED"
	case DuplicateURL:
		return "DUPLICATE_URL"
	case DuplicateEdition:
		return "DUPLICATE_EDITION"
	case StaleURL:
		return "STALE_URL"
	case NotConference:
		return "NOT_CONFERENCE"
	case LowConfidence:
		return "LOW_CONFIDENCE"
	case PastConference:
		return "PAST_CONFERENCE"
	case InvalidPermanent:
		return "INVALID_PERMANENT"
	case Saved:
		return "SAVED"
	case Updated:
		return "UPDATED"
	case FailedExtraction:
		return "FAILED_EXTRACTION"
	case FailedSave:
		return "FAILED_SAVE"
	case FailedValidation:
		return "FAILED_VALIDATION"
	}
	return "UNKNOWN"
}

// minConfidence is the floor below which an extraction is rejected.
const minConfidence = 0.75

// notifyWindowDays is how far ahead a saved conference is announced.
const notifyWindowDays = 30

// statusFlushEvery is how many statuses the writer buffers before flushing.
const statusFlushEvery = 50

// terminalStatus maps each outcome to the seen_links status to persist. A nil
// pointer means "no write" (the Python _TERMINAL_STATUS values).
var terminalStatus = map[Outcome]*string{
	DuplicateURL:     ptr("extracted"),
	DuplicateEdition: ptr("extracted"),
	StaleURL:         ptr("not_conference"),
	NotConference:    ptr("not_conference"),
	LowConfidence:    ptr("low_confidence"),
	PastConference:   ptr("not_conference"),
	InvalidPermanent: ptr("low_confidence"),
	Saved:            ptr("extracted"),
	Updated:          ptr("extracted"),
	FailedExtraction: ptr("failed_transient"),
	FailedValidation: ptr("failed_transient"),
}

// skippedOutcomes are tallied as skipped rather than saved/failed.
var skippedOutcomes = map[Outcome]bool{
	AlreadyDecided: true, DuplicateURL: true, DuplicateEdition: true,
	StaleURL: true, NotConference: true, LowConfidence: true,
	PastConference: true, InvalidPermanent: true, Updated: true,
}

func ptr(s string) *string { return &s }
