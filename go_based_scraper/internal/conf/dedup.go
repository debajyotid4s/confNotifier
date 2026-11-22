// In-memory dedup index over conference records.
package conf

import "time"

// ConferenceIndex provides fast duplicate detection via URL and edition lookups.
//
// Loaded once per run (a few hundred rows) and consulted before every LLM
// call, so a duplicate costs a dict lookup instead of a Gemini request.
type ConferenceIndex struct {
	byURL     map[string]int
	byEdition map[string]int
}

// NewConferenceIndex creates an empty index.
func NewConferenceIndex() *ConferenceIndex {
	return &ConferenceIndex{
		byURL:     make(map[string]int),
		byEdition: make(map[string]int),
	}
}

// Add records a conference into the index.
func (idx *ConferenceIndex) Add(confID int, website, title string,
	dateStart time.Time, deadlines []time.Time,
) {
	if website != "" {
		idx.byURL[CanonicalURL(website)] = confID
	}
	key := EditionKey(title, dateStart, website, deadlines)
	if key != "" {
		if _, ok := idx.byEdition[key]; !ok {
			idx.byEdition[key] = confID
		}
	}
}

// FindByURL returns the existing conference id for this URL, or 0.
func (idx *ConferenceIndex) FindByURL(url string) int {
	if url == "" {
		return 0
	}
	return idx.byURL[CanonicalURL(url)]
}

// FindByIDentity returns the existing conference id for this title+edition, or 0.
func (idx *ConferenceIndex) FindByIDentity(title string,
	dateStart time.Time, website string, deadlines []time.Time,
) int {
	key := EditionKey(title, dateStart, website, deadlines)
	if key == "" {
		return 0
	}
	return idx.byEdition[key]
}

// Find returns an existing conference id matching either URL or identity, or 0.
func (idx *ConferenceIndex) Find(url, title string,
	dateStart time.Time, deadlines []time.Time,
) int {
	if url != "" {
		if hit := idx.FindByURL(url); hit != 0 {
			return hit
		}
	}
	if title != "" {
		if hit := idx.FindByIDentity(title, dateStart, url, deadlines); hit != 0 {
			return hit
		}
	}
	return 0
}

// Len returns the number of URLs in the index.
func (idx *ConferenceIndex) Len() int {
	return len(idx.byURL)
}
