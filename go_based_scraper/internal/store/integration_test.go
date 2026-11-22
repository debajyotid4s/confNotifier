// Integration tests for store package.
//go:build integration

package store

import (
	"context"
	"os"
	"testing"
	"time"
)

func testPool(t *testing.T) *Pool {
	t.Helper()
	dsn := os.Getenv("TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("TEST_DATABASE_URL not set")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	p, err := NewPool(ctx)
	if err != nil {
		t.Fatalf("new pool: %v", err)
	}
	return p
}

func TestLoadConferenceIndex(t *testing.T) {
	ctx := context.Background()
	p := testPool(t)
	_, err := LoadConferenceIndex(ctx, p)
	if err != nil {
		t.Fatalf("load index: %v", err)
	}
}

func TestLoadTerminalURLs(t *testing.T) {
	ctx := context.Background()
	p := testPool(t)
	urls, err := LoadTerminalURLs(ctx, p)
	if err != nil {
		t.Fatalf("load terminal: %v", err)
	}
	_ = urls
}

func TestLoadPendingURLs(t *testing.T) {
	ctx := context.Background()
	p := testPool(t)
	urls, err := LoadPendingURLs(ctx, p)
	if err != nil {
		t.Fatalf("load pending: %v", err)
	}
	_ = urls
}

func TestSaveSeenLinksBulk(t *testing.T) {
	ctx := context.Background()
	p := testPool(t)
	n, err := SaveSeenLinksBulk(ctx, p, []SeenLink{
		{URL: "https://example.com/cfp1", Source: "test", Status: "pending"},
		{URL: "https://example.com/cfp2", Source: "test", Status: "pending"},
	})
	if err != nil {
		t.Fatalf("save bulk: %v", err)
	}
	if n != 2 {
		t.Errorf("expected 2, got %d", n)
	}
}

func TestMarkURLStatus(t *testing.T) {
	ctx := context.Background()
	p := testPool(t)
	err := MarkURLStatus(ctx, p, "https://example.com/test", "extracted")
	if err != nil {
		t.Fatalf("mark status: %v", err)
	}
	ok, err := IsURLProcessed(ctx, p, "https://example.com/test")
	if err != nil {
		t.Fatalf("is processed: %v", err)
	}
	if !ok {
		t.Error("expected URL to be processed")
	}
}

func TestLoadDomainStrategies(t *testing.T) {
	ctx := context.Background()
	p := testPool(t)
	_, err := LoadDomainStrategies(ctx, p)
	if err != nil {
		t.Fatalf("load strategies: %v", err)
	}
}

func TestSaveDomainStrategy(t *testing.T) {
	ctx := context.Background()
	p := testPool(t)
	err := SaveDomainStrategy(ctx, p, "example.com", "stdlib", "https://example.com")
	if err != nil {
		t.Fatalf("save strategy: %v", err)
	}
}

func TestGetTaskLastRun(t *testing.T) {
	ctx := context.Background()
	p := testPool(t)
	_, err := GetTaskLastRun(ctx, p, "deadline_verification")
	if err != nil {
		t.Fatalf("get task last run: %v", err)
	}
}

func TestMarkVerificationDone(t *testing.T) {
	ctx := context.Background()
	p := testPool(t)
	err := MarkVerificationDone(ctx, p)
	if err != nil {
		t.Fatalf("mark verification done: %v", err)
	}
}

func TestMarkNotified(t *testing.T) {
	ctx := context.Background()
	p := testPool(t)
	// Should succeed even if conf_id doesn't exist (no rows affected)
	err := MarkNotified(ctx, p, 999999)
	if err != nil {
		t.Fatalf("mark notified: %v", err)
	}
}
