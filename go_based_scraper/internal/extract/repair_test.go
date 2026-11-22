package extract

import "testing"

func TestRepairJSONValid(t *testing.T) {
	out, err := RepairJSON(`{"a": 1}`)
	if err != nil {
		t.Fatalf("err: %v", err)
	}
	if out["a"].(float64) != 1 {
		t.Errorf("a = %v", out["a"])
	}
}

func TestRepairJSONFenced(t *testing.T) {
	out, err := RepairJSON("```json\n{\"a\": 1}\n```")
	if err != nil {
		t.Fatalf("err: %v", err)
	}
	if _, ok := out["a"]; !ok {
		t.Errorf("missing a: %v", out)
	}
}

func TestRepairJSONTrailingComma(t *testing.T) {
	out, err := RepairJSON(`{"a": 1,}`)
	if err != nil {
		t.Fatalf("err: %v", err)
	}
	if out["a"].(float64) != 1 {
		t.Errorf("a = %v", out["a"])
	}
}

func TestRepairJSONTruncated(t *testing.T) {
	// Cut off mid-object; the closer should re-balance.
	out, err := RepairJSON(`{"a": 1, "b": {"c": 2, "d":`)
	if err != nil {
		t.Fatalf("err: %v", err)
	}
	if out["a"].(float64) != 1 {
		t.Errorf("a = %v", out["a"])
	}
}

func TestRepairJSONEmpty(t *testing.T) {
	if _, err := RepairJSON("   "); err == nil {
		t.Error("expected error for empty")
	}
}

func TestRepairJSONGarbage(t *testing.T) {
	if _, err := RepairJSON("not json at all"); err == nil {
		t.Error("expected error for unparseable")
	}
}

func TestCloseTruncatedClosesArray(t *testing.T) {
	// Matches the Python algorithm: it closes at the last comma, dropping the
	// dangling final element.
	got := closeTruncated(`["a", "b", "c"`)
	if got != `["a", "b"]` {
		t.Errorf("got %q", got)
	}
}
