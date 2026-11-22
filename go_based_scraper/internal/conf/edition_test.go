// Tests for edition identity and ConferenceIndex.
package conf

import (
	"testing"
	"time"
)

func TestEditionYear(t *testing.T) {
	d2027 := time.Date(2027, 3, 1, 0, 0, 0, 0, time.UTC)
	dl := []time.Time{time.Date(2027, 1, 5, 0, 0, 0, 0, time.UTC)}

	if got := EditionYear("ICCIT 2026", "", d2027, nil); got != 2027 {
		t.Errorf("EditionYear date_start = %d, want 2027", got)
	}
	if got := EditionYear("ICCIT", "", time.Time{}, dl); got != 2027 {
		t.Errorf("EditionYear deadline = %d, want 2027", got)
	}
	if got := EditionYear("ICCIT 2027", "", time.Time{}, nil); got != 2027 {
		t.Errorf("EditionYear title = %d, want 2027", got)
	}
	if got := EditionYear("ICCIT", "https://iccit.org.bd/2027/", time.Time{}, nil); got != 2027 {
		t.Errorf("EditionYear website = %d, want 2027", got)
	}
	if got := EditionYear("ICCIT", "", time.Time{}, nil); got != 0 {
		t.Errorf("EditionYear unknown = %d, want 0", got)
	}
}

func TestEditionKey(t *testing.T) {
	d2027 := time.Date(2027, 12, 1, 0, 0, 0, 0, time.UTC)

	a := EditionKey("ICCIT 2027", d2027, "https://iccit.org.bd/2027/", nil)
	b := EditionKey("3rd International Conference (ICCIT 2027)", d2027,
		"https://iccit2027.cse.buet.ac.bd/", nil)
	if a != "iccit:2027" || b != "iccit:2027" {
		t.Errorf("EditionKey same edition: a=%q b=%q, want both=%q", a, b, "iccit:2027")
	}
	ka := EditionKey("ICCIT 2027", time.Date(2027, 1, 1, 0, 0, 0, 0, time.UTC), "", nil)
	kb := EditionKey("ICCIT 2028", time.Date(2028, 1, 1, 0, 0, 0, 0, time.UTC), "", nil)
	if ka == kb {
		t.Errorf("EditionKey different editions: a=%q b=%q, want different", ka, kb)
	}
	if got := EditionKey("", d2027, "", nil); got != "" {
		t.Errorf("EditionKey empty title = %q, want empty", got)
	}
}
