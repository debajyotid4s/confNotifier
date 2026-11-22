// Tests for conference URL classification — accepted URLs.
package conf

import (
	"testing"
	"time"
)

var classifyNow = time.Date(2026, 6, 15, 0, 0, 0, 0, time.UTC)

func accepted(url string) (bool, string) {
	return ClassifyLink(url, classifyNow)
}

func TestClassifyLink_AcceptsRealConferences(t *testing.T) {
	urls := []string{
		"https://iccit.org.bd/2027/home/",
		"https://icerie.sust.edu/",
		"https://icmiee2027.kuet.ac.bd/",
		"https://becithcon.org/2027/",
		"https://spicscon.org/",
		"https://peeiacon.org/2027/",
		"https://raaicon.org/",
		"https://qpain.org/",
		"https://icaeee.ruet.ac.bd/",
		"https://www.cuet.ac.bd/conference-2027/",
		"https://du.ac.bd/symposium-2027",
		"https://buet.ac.bd/icche/call-for-papers",
		"https://nstu.edu.bd/cfp/",
		"https://aiub.edu/paper-submission-guidelines",
		"https://ieeebd2027.org/",
		"https://jurs.info/jicirsigc-2027",
	}
	for _, url := range urls {
		ok, reason := accepted(url)
		if !ok {
			t.Errorf("accepted(%q) = false, reason %q; want true", url, reason)
		}
	}
}
