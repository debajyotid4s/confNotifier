// Package config loads and validates all required environment variables.
// Load() returns one error listing every missing variable (whitespace-only counts).
package config

import (
	"fmt"
	"os"
	"strings"
)

// Required lists every environment variable the system needs to start.
// All known vars from the Python code are included; non-ported vars are omitted.
var required = []string{
	"DATABASE_URL",
	"OPENAI_API_KEY",
	"OPENAI_BASE_URL",
	"NOTIFY_SECRET",
	"JWT_SECRET",
	"PORT",
}

// Optional lists environment variables that, when empty, are allowed (they
// only gate features that aren't needed for a scrape run).
var optional = []string{
	"TELEGRAM_BOT_TOKEN",
	"TELEGRAM_CHANNEL_ID",
	"TELEGRAM_CHANNEL_LINK",
}

// Config holds the loaded environment values.
type Config struct {
	DatabaseURL      string
	OpenAIKey        string
	OpenAIBaseURL    string
	TelegramBotToken string
	NotifySecret     string
	JWTSecret        string
	Port             string
}

// Load reads all required environment variables.
// Returns one error listing every missing or whitespace-only variable.
func Load() (*Config, error) {
	var missing []string
	c := &Config{}

	check("DATABASE_URL", &c.DatabaseURL, &missing)
	check("OPENAI_API_KEY", &c.OpenAIKey, &missing)
	check("OPENAI_BASE_URL", &c.OpenAIBaseURL, &missing)
	check("TELEGRAM_BOT_TOKEN", &c.TelegramBotToken, &missing)
	check("NOTIFY_SECRET", &c.NotifySecret, &missing)
	check("JWT_SECRET", &c.JWTSecret, &missing)
	check("PORT", &c.Port, &missing)

	if len(missing) > 0 {
		return nil, fmt.Errorf("missing environment variables: %s", strings.Join(missing, ", "))
	}
	return c, nil
}

// isOptional reports whether a variable may be left blank.
func isOptional(name string) bool {
	for _, o := range optional {
		if o == name {
			return true
		}
	}
	return false
}

// check reads one env var. If missing or whitespace-only, records its name.
func check(name string, target *string, missing *[]string) {
	val := os.Getenv(name)
	if strings.TrimSpace(val) == "" {
		if isOptional(name) {
			return
		}
		*missing = append(*missing, name)
		return
	}
	*target = val
}
