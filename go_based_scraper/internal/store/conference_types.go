// Conference types and dedup index.
package store

// DeadlineTypes are the deadline kinds tracked in the DB.
var DeadlineTypes = []string{
	"abstract", "full_paper", "notification_of_acceptance",
	"camera_ready", "registration",
}

// ConferenceRow represents a conference row returned by the DB.
type ConferenceRow struct {
	ID          int
	Title       string
	DateStart   string
	DateEnd     *string
	City        *string
	Country     string
	Website     string
	Organizer   *string
	Category    *string
	Description *string
}

// ConferenceIndex holds the in-memory dedup index.
type ConferenceIndex struct {
	ByURL     map[string]int // website -> conference_id
	ByEdition map[string]int // edition_key -> conference_id
}

// NewConferenceIndex creates an empty index.
func NewConferenceIndex() *ConferenceIndex {
	return &ConferenceIndex{
		ByURL:     make(map[string]int),
		ByEdition: make(map[string]int),
	}
}

// Add adds a conference to the index.
func (ci *ConferenceIndex) Add(id int, website, title, dateStart string, deadlines []any) {
	ci.ByURL[website] = id
	key := editionKey(website, title, dateStart)
	ci.ByEdition[key] = id
}

// Len returns how many conferences are in the dedup index.
func (ci *ConferenceIndex) Len() int {
	return len(ci.ByURL)
}

// FindByUrl returns the conference id for a website, or 0 if absent.
func (ci *ConferenceIndex) FindByUrl(website string) int {
	return ci.ByURL[website]
}

// FindByIdentity returns the conference id for an edition key, or 0 if absent.
func (ci *ConferenceIndex) FindByIdentity(key string) int {
	return ci.ByEdition[key]
}

func editionKey(website, title, dateStart string) string {
	return website + "|" + title + "|" + dateStart
}
