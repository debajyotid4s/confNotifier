package extract

import (
	"context"
	"strings"
	"time"

	"confnotifier/internal/conf"
)

const (
	maxTextChars     = 14000
	minPageTextChars = 100
)

// ExtractResult is the normalised extraction: a flat map the pipeline passes
// straight to the store.
type ExtractResult = map[string]any

// ExtractConferences turns page text into a normalised conference record, or
// returns nil when the text is too short to be worth sending to the model.
//
// It is the Go port of scraper/extraction/core.py:extract_conferences.
func ExtractConferences(pageText, sourceURL string, previousDeadlines map[string]any, now time.Time, client *Client) (ExtractResult, error) {
	if strings.TrimSpace(pageText) == "" || len(strings.TrimSpace(pageText)) < minPageTextChars {
		return nil, nil
	}
	focused := conf.FocusText(pageText, maxTextChars, 0)
	userContent := "Source URL: " + sourceURL + "\n\nPage content:\n" + focused
	if block := formatPreviousDeadlines(previousDeadlines); block != "" {
		userContent += block
	}
	parsed, err := client.Complete(context.Background(), SystemPrompt, userContent, ExtractionSchemaJSON)
	if err != nil {
		return nil, err
	}
	return conf.NormalizeExtraction(parsed, now), nil
}

// formatPreviousDeadlines renders stored deadlines as explicitly-untrusted
// context for re-extraction (scraper/extraction/core.py::_format_previous_deadlines).
func formatPreviousDeadlines(previous map[string]any) string {
	if len(previous) == 0 {
		return ""
	}
	var lines []string
	for _, typ := range conf.DeadlineTypes {
		old, ok := previous[typ]
		if !ok {
			continue
		}
		var date string
		switch v := old.(type) {
		case map[string]any:
			if d, ok := v["date"].(string); ok {
				date = d
			}
		case string:
			date = v
		}
		if date == "" {
			continue
		}
		lines = append(lines, "  - "+conf.DeadlineLabels[typ]+": "+date)
	}
	if len(lines) == 0 {
		return ""
	}
	return "\n\nPreviously recorded deadlines from our database (these MAY BE OUTDATED — " +
		"the page may have been updated since):\n" + strings.Join(lines, "\n") +
		"\nExtract the dates the page shows RIGHT NOW. Do not repeat a value above " +
		"unless the page still displays it. If the page shows a later date for the " +
		"same deadline, that is an extension — return the later date."
}
