package config

import "testing"

func TestLoad_allPresent(t *testing.T) {
	t.Setenv("DATABASE_URL", "postgres://x")
	t.Setenv("OPENAI_API_KEY", "key1")
	t.Setenv("OPENAI_BASE_URL", "key2")
	t.Setenv("TELEGRAM_BOT_TOKEN", "bot")
	t.Setenv("TELEGRAM_BOT_TOKEN", "bot")
	t.Setenv("NOTIFY_SECRET", "notify")
	t.Setenv("JWT_SECRET", "jwt")
	t.Setenv("PORT", "8080")

	c, err := Load()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if c.Port != "8080" {
		t.Errorf("Port = %q, want %q", c.Port, "8080")
	}
}

func TestLoad_missingOne(t *testing.T) {
	t.Setenv("DATABASE_URL", "postgres://x")
	t.Setenv("OPENAI_API_KEY", "key1")
	t.Setenv("OPENAI_BASE_URL", "key2")
	t.Setenv("NOTIFY_SECRET", "notify")
	t.Setenv("PORT", "8080")

	_, err := Load()
	if err == nil {
		t.Fatal("expected error for missing JWT_SECRET")
	}
	if got := err.Error(); !containsStr(got, "JWT_SECRET") {
		t.Errorf("error = %q, want to contain JWT_SECRET", got)
	}
}

func TestLoad_portWhitespace(t *testing.T) {
	t.Setenv("DATABASE_URL", "postgres://x")
	t.Setenv("OPENAI_API_KEY", "key1")
	t.Setenv("OPENAI_BASE_URL", "key2")
	t.Setenv("TELEGRAM_BOT_TOKEN", "bot")
	t.Setenv("TELEGRAM_BOT_TOKEN", "bot")
	t.Setenv("NOTIFY_SECRET", "notify")
	t.Setenv("JWT_SECRET", "jwt")
	t.Setenv("PORT", "  ")

	_, err := Load()
	if err == nil {
		t.Fatal("expected error for whitespace-only PORT")
	}
	if got := err.Error(); !containsStr(got, "PORT") {
		t.Errorf("error = %q, want to contain PORT", got)
	}
}
