// Tests for title normalisation helpers.
package conf

import "testing"

func TestAcronymFromTitle(t *testing.T) {
	tests := []struct {
		title, want string
	}{
		{"3rd International Conference on Computing (ICCIT 2027)", "ICCIT"},
		{"International Conference on Electrical Engineering (ICECE)", "ICECE"},
		{"ICMIEE 2027", "ICMIEE"},
		{"IEEE International Conference (BECITHCON 2027)", "BECITHCON"},
	}
	for _, tt := range tests {
		got := AcronymFromTitle(tt.title)
		if got != tt.want {
			t.Errorf("AcronymFromTitle(%q) = %q, want %q", tt.title, got, tt.want)
		}
	}
	if got := AcronymFromTitle("IEEE International Conference on Things"); got != "" {
		t.Errorf("AcronymFromTitle = %q, want empty (IEEE is a stopword)", got)
	}
	if got := AcronymFromTitle(""); got != "" {
		t.Errorf("AcronymFromTitle(\"\") = %q, want empty", got)
	}
}

func TestTitleKey(t *testing.T) {
	tests := []struct {
		title, want string
	}{
		{"3rd International Conference on X (ICCIT 2027)", "iccit"},
		{"International Conference on Computing and Information Technology", "computinginformationtechnology"},
		{"5th Annual Robotics Meeting 2027", "robotics"},
		{"", ""},
	}
	for _, tt := range tests {
		got := TitleKey(tt.title)
		if got != tt.want {
			t.Errorf("TitleKey(%q) = %q, want %q", tt.title, got, tt.want)
		}
	}
	a := TitleKey("2nd International Conference on Computing (ICCIT 2027)")
	b := TitleKey("ICCIT 2027 — International Conference on Computing")
	if a != b || a != "iccit" {
		t.Errorf("TitleKey reworded: a=%q b=%q, want both=%q", a, b, "iccit")
	}
}
