package store

import "testing"

// TestRunHolderTokenUnique proves the lock holder token is non-empty and
// process-unique, so two concurrent runs never collide on the same token.
func TestRunHolderTokenUnique(t *testing.T) {
	a := RunHolderToken()
	if a == "" {
		t.Fatal("holder token must not be empty")
	}
	b := RunHolderToken()
	if a == b {
		t.Error("two holder tokens should differ")
	}
}
