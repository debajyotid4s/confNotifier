package discovery

import "testing"

func TestNormalizeCertName(t *testing.T) {
	cases := map[string]string{
		"www.buet.ac.bd":    "www.buet.ac.bd",
		"MAIL.BUET.AC.BD":   "mail.buet.ac.bd",
		"":                  "",
		"foo\\bar.ac.bd":    "",
		"  eee.buet.ac.bd ": "eee.buet.ac.bd",
	}
	for in, want := range cases {
		if got := normalizeCertName(in); got != want {
			t.Errorf("normalizeCertName(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestIsConferenceDomain(t *testing.T) {
	ok := []string{"buet.ac.bd", "iu.ac.bd", "cse.buet.ac.bd", "conf.edu.bd"}
	for _, d := range ok {
		if !isConferenceDomain(d) {
			t.Errorf("isConferenceDomain(%q) = false, want true", d)
		}
	}
	bad := []string{"mail.buet.ac.bd", "example.com", "abc.edu", "vpn.buet.ac.bd"}
	for _, d := range bad {
		if isConferenceDomain(d) {
			t.Errorf("isConferenceDomain(%q) = true, want false", d)
		}
	}
}

func TestDefaultQueries(t *testing.T) {
	c := NewClient(nil)
	if len(c.queries) == 0 {
		t.Fatal("expected default queries")
	}
}
