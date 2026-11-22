// Tests for ConferenceIndex.
package conf

import (
	"testing"
	"time"
)

func TestConferenceIndex(t *testing.T) {
	idx := NewConferenceIndex()
	d2027 := time.Date(2027, 12, 1, 0, 0, 0, 0, time.UTC)
	d2028 := time.Date(2028, 12, 1, 0, 0, 0, 0, time.UTC)

	idx.Add(1, "https://iccit.org.bd/2027/home/", "ICCIT 2027", d2027, nil)
	idx.Add(2, "https://icerie.sust.edu/", "ICERIE 2027", d2027, nil)

	if got := idx.FindByURL("http://www.iccit.org.bd/2027/index.html"); got != 1 {
		t.Errorf("FindByURL variant = %d, want 1", got)
	}
	if got := idx.Find("https://iccit2027.cse.buet.ac.bd/",
		"3rd Intl Conference (ICCIT 2027)", d2027, nil); got != 1 {
		t.Errorf("FindByIdentity = %d, want 1", got)
	}
	if got := idx.Find("https://brand-new.org/", "ICNEW 2027", d2027, nil); got != 0 {
		t.Errorf("Find miss = %d, want 0", got)
	}
	if got := idx.Find("https://iccit.org.bd/2028/", "ICCIT 2028", d2028, nil); got != 0 {
		t.Errorf("Next edition = %d, want 0", got)
	}
	if got := idx.Len(); got != 2 {
		t.Errorf("Len = %d, want 2", got)
	}
}
