// Tests for URL canonicalisation.
package conf

import "testing"

func TestCanonicalURL(t *testing.T) {
	tests := []struct {
		input, want string
	}{
		{"http://iccit.org.bd/2027/home/", "https://iccit.org.bd/2027"},
		{"https://www.iccit.org.bd/2027/home", "https://iccit.org.bd/2027"},
		{"https://ICCIT.org.bd/2027/index.html", "https://iccit.org.bd/2027"},
		{"https://iccit.org.bd/2027/", "https://iccit.org.bd/2027"},
		{"https://iccit.org.bd//2027//home//", "https://iccit.org.bd/2027"},
		{"https://iccit.org.bd/2027/home/#schedule", "https://iccit.org.bd/2027"},
		{"https://iccit.org.bd/2027/home/?utm_source=twitter", "https://iccit.org.bd/2027"},
		{"https://iccit.org.bd/2027/default.php", "https://iccit.org.bd/2027"},
		{"https://x.org/p?b=2&a=1", "https://x.org/p?a=1&b=2"},
		{"https://x.org/p?utm_medium=x&fbclid=y", "https://x.org/p"},
		{"not a url", "not a url"},
		{"", ""},
	}
	for _, tt := range tests {
		got := CanonicalURL(tt.input)
		if got != tt.want {
			t.Errorf("CanonicalURL(%q) = %q, want %q", tt.input, got, tt.want)
		}
	}
}

func TestSameURL(t *testing.T) {
	if !SameURL("http://www.X.org/home/", "https://x.org") {
		t.Error("SameURL: expected true for equivalent URLs")
	}
	if SameURL("https://x.org/a", "https://x.org/b") {
		t.Error("SameURL: expected false for different paths")
	}
	if SameURL("", "https://x.org") {
		t.Error("SameURL: expected false for empty input")
	}
}
