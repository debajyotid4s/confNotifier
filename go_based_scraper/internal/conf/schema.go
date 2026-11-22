// Conference data model and JSON unmarshalling.
package conf

// Conference is the flat shape the pipeline expects after extraction + sanitization.
type Conference struct {
	IsConference bool    `json:"is_conference"`
	Title        string  `json:"title"`
	DateStart    *string `json:"date_start"`
	DateEnd      *string `json:"date_end"`
	City         *string `json:"city"`
	Country      string  `json:"country"`
	Website      string  `json:"website"`
	Organizer    *string `json:"organizer"`
	Category     string  `json:"category"`
	Description  *string `json:"description"`
	Confidence   float64 `json:"confidence"`

	AbstractDeadline      *string `json:"abstract_deadline"`
	AbstractDeadlineLabel string  `json:"abstract_deadline_label"`
	AbstractDeadlineCtx   *string `json:"abstract_deadline_context"`

	FullPaperDeadline      *string `json:"full_paper_deadline"`
	FullPaperDeadlineLabel string  `json:"full_paper_deadline_label"`
	FullPaperDeadlineCtx   *string `json:"full_paper_deadline_context"`

	SanitizeNotes []string `json:"sanitize_notes,omitempty"`
}

// ExtractedDeadline holds a deadline with its page context.
type ExtractedDeadline struct {
	Date    *string `json:"date"`
	Context string  `json:"context"`
}
