package config

import "testing"

func TestLoad_apiDoesNotNeedLLMCreds(t *testing.T) {
	// The API process must start without scraper-only LLM credentials.
	t.Setenv("DATABASE_URL", "postgres://x")
	t.Setenv("JWT_SECRET", "jwt")
	t.Setenv("NOTIFY_SECRET", "notify")
	t.Setenv("PORT", "8080")

	c, err := LoadAPIConfig()
	if err != nil {
		t.Fatalf("LoadAPIConfig failed without OPENAI_*: %v", err)
	}
	if c.Port != "8080" {
		t.Errorf("Port = %q, want %q", c.Port, "8080")
	}
}

func TestLoad_apiStillRequiresItsOwnVars(t *testing.T) {
	// API config still enforces its own required variables.
	t.Setenv("DATABASE_URL", "postgres://x")
	t.Setenv("JWT_SECRET", "jwt")
	t.Setenv("NOTIFY_SECRET", "notify")

	_, err := LoadAPIConfig()
	if err == nil {
		t.Fatal("expected error for missing PORT")
	}
	if got := err.Error(); !containsStr(got, "PORT") {
		t.Errorf("error = %q, want to contain PORT", got)
	}
}

func TestLoad_stillRequiresLLMCreds(t *testing.T) {
	// The full loader is unchanged: it still requires OPENAI_* (scraper/verify).
	t.Setenv("DATABASE_URL", "postgres://x")
	t.Setenv("NOTIFY_SECRET", "notify")
	t.Setenv("JWT_SECRET", "jwt")
	t.Setenv("PORT", "8080")

	_, err := Load()
	if err == nil {
		t.Fatal("expected error for missing OPENAI_API_KEY")
	}
	if got := err.Error(); !containsStr(got, "OPENAI_API_KEY") {
		t.Errorf("error = %q, want to contain OPENAI_API_KEY", got)
	}
}

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
