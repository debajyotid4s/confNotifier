package config

import "testing"

func TestLoad_missingSeveral(t *testing.T) {
	t.Setenv("DATABASE_URL", "postgres://x")
	t.Setenv("OPENAI_API_KEY", "key1")
	t.Setenv("OPENAI_BASE_URL", "key2")
	t.Setenv("TELEGRAM_BOT_TOKEN", "")

	_, err := Load()
	if err == nil {
		t.Fatal("expected error for multiple missing vars")
	}
	got := err.Error()
	if !containsStr(got, "JWT_SECRET") {
		t.Errorf("error = %q, want to contain JWT_SECRET", got)
	}
	if !containsStr(got, "NOTIFY_SECRET") {
		t.Errorf("error = %q, want to contain NOTIFY_SECRET", got)
	}
}

// Telegram is optional: an empty token must not fail Load.
func TestLoad_telegramOptional(t *testing.T) {
	t.Setenv("DATABASE_URL", "postgres://x")
	t.Setenv("OPENAI_API_KEY", "key1")
	t.Setenv("OPENAI_BASE_URL", "key2")
	t.Setenv("TELEGRAM_BOT_TOKEN", "")
	t.Setenv("NOTIFY_SECRET", "notify")
	t.Setenv("JWT_SECRET", "jwt")
	t.Setenv("PORT", "8080")

	c, err := Load()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if c.TelegramBotToken != "" {
		t.Errorf("TelegramBotToken = %q, want empty", c.TelegramBotToken)
	}
}

func TestLoad_whitespaceOnly(t *testing.T) {
	t.Setenv("DATABASE_URL", "postgres://x")
	t.Setenv("OPENAI_API_KEY", "key1")
	t.Setenv("OPENAI_BASE_URL", "key2")
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

func TestLoad_emptyEnv(t *testing.T) {
	for _, k := range required {
		t.Setenv(k, "")
	}

	_, err := Load()
	if err == nil {
		t.Fatal("expected error when all vars are empty")
	}
	got := err.Error()
	for _, name := range required {
		if !containsStr(got, name) {
			t.Errorf("error = %q, want to contain %q", got, name)
		}
	}
}

func containsStr(s, substr string) bool {
	for i := 0; i <= len(s)-len(substr); i++ {
		if s[i:i+len(substr)] == substr {
			return true
		}
	}
	return false
}
