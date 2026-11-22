// Tests for conference URL classification — rejected URLs and helpers.
package conf

import (
	"testing"
	"time"
)

var rejectNow = time.Date(2026, 6, 15, 0, 0, 0, 0, time.UTC)

func rejected(url string) (bool, string) {
	return ClassifyLink(url, rejectNow)
}

func TestClassifyLink_RejectsFalsePositives(t *testing.T) {
	tests := []struct {
		url, reason string
	}{
		{"https://falcon.com/", "no_signal"},
		{"https://bacon.net/recipes", "no_signal"},
		{"https://telecon.xyz/", "no_signal"},
		{"https://facebook.com/somesymposium", "blocked_host"},
		{"https://m.facebook.com/events/symposium-2027", "blocked_host"},
		{"https://youtube.com/watch?v=conference2027", "blocked_host"},
		{"https://en.wikipedia.org/wiki/Symposium", "blocked_host"},
		{"https://link.springer.com/conference/iccit", "blocked_host"},
		{"https://easychair.org/conferences/?conf=iccit2027", "blocked_host"},
		{"https://du.ac.bd/notice/seminar-2027", "junk_segment"},
		{"https://ru.ac.bd/news/conference-2027-report", "junk_segment"},
		{"https://cu.ac.bd/gallery/symposium-2027", "junk_segment"},
		{"https://ku.ac.bd/admission/exam-2027", "junk_segment"},
		{"https://buet.ac.bd/iccit-2027-cfp.pdf", "non_html"},
		{"https://sust.edu/conference-2027/banner.jpg", "non_html"},
		{"https://icap2019.sust.edu/", "stale_year"},
		{"https://iccit.org.bd/2015/home/", "stale_year"},
		{"https://icerie.sust.edu/past-conferences", "stale_wording"},
		{"https://becithcon.org/proceedings", "stale_wording"},
		{"https://du.ac.bd/seminar/", "weak_signal_no_year"},
		{"ftp://iccit.org.bd/2027/", "bad_scheme"},
		{"", "empty"},
		{"not a url", "bad_scheme"},
	}
	for _, tt := range tests {
		ok, reason := rejected(tt.url)
		if ok {
			t.Errorf("rejected(%q) = true, reason %q; want false", tt.url, reason)
		}
		if reason != tt.reason {
			t.Errorf("rejected(%q) reason = %q, want %q", tt.url, reason, tt.reason)
		}
	}
}

func TestIsHTMLURL(t *testing.T) {
	if !IsHTMLURL("https://x.org/page") {
		t.Error("IsHTMLURL: expected true for HTML page")
	}
	if IsHTMLURL("https://x.org/file.pdf") {
		t.Error("IsHTMLURL: expected false for PDF")
	}
	if IsHTMLURL("https://x.org/style.CSS") {
		t.Error("IsHTMLURL: expected false for CSS")
	}
}

func TestIsBlockedHost(t *testing.T) {
	if !IsBlockedHost("facebook.com") {
		t.Error("IsBlockedHost: expected true for facebook.com")
	}
	if !IsBlockedHost("www.facebook.com") {
		t.Error("IsBlockedHost: expected true for www.facebook.com")
	}
	if !IsBlockedHost("m.facebook.com") {
		t.Error("IsBlockedHost: expected true for m.facebook.com")
	}
	if IsBlockedHost("iccit.org.bd") {
		t.Error("IsBlockedHost: expected false for iccit.org.bd")
	}
}
