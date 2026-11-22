package notify

import (
	"testing"
	"time"
)

func TestHashtag(t *testing.T) {
	cases := map[string]string{
		"ICCIT 2027":     "ICCIT2027",
		"Computing Info": "ComputingInfo",
		"a/b/c":          "Abc",
		"":               "",
		"  spaced  ":     "Spaced",
	}
	for in, want := range cases {
		if got := hashtag(in); got != want {
			t.Errorf("hashtag(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestFormatDate(t *testing.T) {
	cases := []struct {
		in   any
		want string
	}{
		{nil, "TBA"},
		{"", "TBA"},
		{"2027-08-15", "August 15, 2027"},
		{time.Date(2027, 8, 15, 0, 0, 0, 0, time.UTC), "August 15, 2027"},
		{"not a date", "not a date"},
	}
	for _, c := range cases {
		if got := formatDate(c.in); got != c.want {
			t.Errorf("formatDate(%v) = %q, want %q", c.in, got, c.want)
		}
	}
}

func TestDeadlineValue(t *testing.T) {
	conf := map[string]any{
		"abstract_deadline":   "2027-01-15",
		"full_paper_deadline": map[string]any{"date": "2027-02-01", "context": "page"},
	}
	if got := deadlineValue(conf, "abstract_deadline"); got != "2027-01-15" {
		t.Errorf("abstract = %q", got)
	}
	if got := deadlineValue(conf, "full_paper_deadline"); got != "2027-02-01" {
		t.Errorf("full_paper = %q", got)
	}
	if got := deadlineValue(conf, "missing_deadline"); got != "" {
		t.Errorf("missing = %q", got)
	}
}

func TestShortTitle(t *testing.T) {
	cases := []struct {
		in, want string
	}{
		{"3rd International Conference on Computing (ICCIT 2027)", "3rd International Conference on Computing"},
		{"Foo, Bar", "Foo"},
		{"Foo: Bar", "Foo"},
		{"Foo (Bar)", "Foo"},
		{"", ""},
	}
	for _, c := range cases {
		if got := shortTitle(c.in, 0); got != c.want {
			t.Errorf("shortTitle(%q) = %q, want %q", c.in, got, c.want)
		}
	}
}

func TestEscapeHTML(t *testing.T) {
	if got := escapeHTML("<b>&\"'</b>"); got != "&lt;b&gt;&amp;&#34;&#39;&lt;/b&gt;" {
		t.Errorf("escapeHTML = %q", got)
	}
	if got := escapeHTML(nil); got != "" {
		t.Errorf("escapeHTML(nil) = %q", got)
	}
}

func TestBuildConferenceMessage(t *testing.T) {
	conf := map[string]any{
		"title":               "International Conference on Computing (ICCIT 2027)",
		"date_start":          "2027-05-01",
		"city":                "Dhaka",
		"organizer":           "BRAC University",
		"category":            "Computing",
		"description":         "A conference on computing.",
		"website":             "https://iccit.bracu.ac.bd",
		"abstract_deadline":   "2027-02-01",
		"full_paper_deadline": "2027-03-01",
	}
	msg := buildConferenceMessage(conf)
	for _, want := range []string{
		"🔔 New International Conference — Bangladesh",
		"📌 International Conference on Computing (ICCIT 2027)",
		"📅 May 1, 2027",
		"⏰ Abstract:",
		"📍 Dhaka, Bangladesh",
		"#Bangladesh",
		"<i>A conference on computing.</i>",
		"iccit.bracu.ac.bd",
	} {
		if !contains(msg, want) {
			t.Errorf("message missing %q\n---\n%s", want, msg)
		}
	}
	// Description under 400 chars is kept verbatim (italic).
	if !contains(msg, "A conference on computing.") {
		t.Error("expected description text")
	}
}

func TestBuildConferenceMessageSingleDay(t *testing.T) {
	conf := map[string]any{
		"title":      "Test Conf",
		"date_start": "2027-05-01",
		"city":       "Dhaka",
		"website":    "https://example.com",
	}
	msg := buildConferenceMessage(conf)
	if contains(msg, " to ") {
		t.Error("single-day conference should not render a 'to' range")
	}
	if !contains(msg, "📅 May 1, 2027") {
		t.Errorf("expected single date line, got:\n%s", msg)
	}
}

func TestBuildConferenceMessageTruncatesLongDescription(t *testing.T) {
	long := ""
	for i := 0; i < 100; i++ {
		long += "word "
	}
	conf := map[string]any{
		"title": "T", "city": "C", "website": "https://e.com",
		"description": long,
	}
	msg := buildConferenceMessage(conf)
	// The italic description block must not exceed 400 characters.
	idx := indexOf(msg, "<i>")
	if idx >= 0 {
		end := indexOf(msg[idx:], "</i>")
		if end > 406 { // 400 + "<i></i>" + slack
			t.Errorf("description block too long: %d", end)
		}
	}
}

func TestBuildDeadlineChangeMessage(t *testing.T) {
	old := time.Date(2027, 1, 10, 0, 0, 0, 0, time.UTC)
	new := time.Date(2027, 2, 10, 0, 0, 0, 0, time.UTC)
	msg := buildDeadlineChangeMessage("ICCIT", "https://e.com", []DeadlineChange{
		{Old: &old, New: &new, Label: "Abstract"},
		{Old: nil, New: &new, Label: "Full Paper"}, // skipped: no old
	})
	if !contains(msg, "Deadline Updated") {
		t.Errorf("missing header:\n%s", msg)
	}
	if !contains(msg, "<s>Jan 10</s> → <b>Feb 10</b>") {
		t.Errorf("missing change line:\n%s", msg)
	}
	if contains(msg, "Full Paper") {
		t.Error("first-time discovery (no old) should be skipped")
	}
}

func TestBuildDeadlineChangeMessageEmpty(t *testing.T) {
	msg := buildDeadlineChangeMessage("T", "https://e.com", nil)
	if msg != "" {
		t.Errorf("expected empty message, got %q", msg)
	}
}

func TestRenderReminders(t *testing.T) {
	d1 := time.Date(2027, 8, 20, 0, 0, 0, 0, time.UTC)
	d2 := time.Date(2027, 8, 10, 0, 0, 0, 0, time.UTC)
	msg := renderReminders([]reminderEntry{
		{deadline: d1, website: "https://a.edu", title: "Conf A"},
		{deadline: d2, website: "https://b.edu", title: "Conf B", previous: &d1},
	}, time.Now())
	// Sorted by deadline: Conf B (Aug 10) before Conf A (Aug 20).
	if indexOf(msg, "Conf B") > indexOf(msg, "Conf A") {
		t.Error("entries not sorted by deadline")
	}
	if !contains(msg, "UPCOMING DEADLINES") {
		t.Error("missing header")
	}
	if !contains(msg, "Updated") {
		t.Error("expected updated marker for changed deadline")
	}
	if !contains(msg, "- a.edu") || !contains(msg, "- b.edu") {
		t.Error("expected domain links")
	}
	if !contains(msg, "Last synced:") {
		t.Error("expected sync timestamp")
	}
}

func TestProgressBars(t *testing.T) {
	wantEmpty := "[" + repeat("░", barLen) + "]"
	if got := progressBar(0); got != wantEmpty {
		t.Errorf("progressBar(0) = %q, want %q", got, wantEmpty)
	}
	wantFull := "[" + repeat("█", barLen) + "]"
	if got := progressBar(100); got != wantFull {
		t.Errorf("progressBar(100) = %q, want %q", got, wantFull)
	}
}

func TestAlertBodySingle(t *testing.T) {
	d := time.Date(2027, 8, 25, 0, 0, 0, 0, time.UTC)
	alerts := []Alert{{ConferenceID: 7, Title: "ICCIT", DeadlineType: "full_paper", Reason: ReasonApproach, Deadline: d}}
	body, data := AlertBody(alerts, time.Now())
	if !contains(body, "ICCIT") {
		t.Errorf("body = %q", body)
	}
	if data["screen"] != "calendar" || data["conference_id"] != "7" {
		t.Errorf("data = %v", data)
	}
}

func TestAlertBodyMany(t *testing.T) {
	d := time.Date(2027, 8, 25, 0, 0, 0, 0, time.UTC)
	alerts := []Alert{
		{ConferenceID: 1, Title: "Conf A", DeadlineType: "abstract", Reason: ReasonApproach, Deadline: d},
		{ConferenceID: 2, Title: "Conf B", DeadlineType: "abstract", Reason: ReasonApproach, Deadline: d},
	}
	_, data := AlertBody(alerts, time.Now())
	if data["screen"] != "upcoming" {
		t.Errorf("many alerts should deep-link to upcoming, got %q", data["screen"])
	}
}

func TestAlertBodyUrgent(t *testing.T) {
	d := time.Now().Add(24 * time.Hour)
	alerts := []Alert{
		{ConferenceID: 1, Title: "Urgent A", DeadlineType: "abstract", Reason: ReasonUrgent24h, Deadline: d},
		{ConferenceID: 2, Title: "Later B", DeadlineType: "abstract", Reason: ReasonApproach, Deadline: d},
	}
	body, _ := AlertBody(alerts, time.Now())
	if !contains(body, "tomorrow") {
		t.Errorf("urgent body = %q", body)
	}
}

func TestDigestBody(t *testing.T) {
	morning := digestBody("morning", []DeadlineSample{{Title: "ICCIT", When: "Feb 01"}})
	if !contains(morning, "Good morning") {
		t.Errorf("morning = %q", morning)
	}
	evening := digestBody("evening", nil)
	if !contains(evening, "Evening check-in") {
		t.Errorf("evening = %q", evening)
	}
	if !contains(digestBody("morning", nil), "check today's CFP deadlines") {
		t.Error("empty morning digest")
	}
}

func contains(haystack, needle string) bool {
	return indexOf(haystack, needle) >= 0
}

func indexOf(haystack, needle string) int {
	for i := 0; i+len(needle) <= len(haystack); i++ {
		if haystack[i:i+len(needle)] == needle {
			return i
		}
	}
	return -1
}

func repeat(s string, n int) string {
	var b []byte
	for i := 0; i < n; i++ {
		b = append(b, []byte(s)...)
	}
	return string(b)
}
