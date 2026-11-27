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

// apiRequired lists the variables the REST API process needs. It deliberately
// omits scraper-only credentials (OPENAI_*): the API serves conference data and
// must start in an environment that never sets LLM keys.
var apiRequired = []string{
	"DATABASE_URL",
	"JWT_SECRET",
	"NOTIFY_SECRET",
	"PORT",
}

// Load reads all required (scraper-wide) environment variables.
// Returns one error listing every missing or whitespace-only variable.
func Load() (*Config, error) {
	return loadFor(required)
}

// LoadAPIConfig loads only the variables the REST API process needs. It never
// requires scraper-only credentials, so the API can start alongside the scraper
// (or behind a proxy next to Python) without LLM keys present.
func LoadAPIConfig() (*Config, error) {
	return loadFor(apiRequired)
}

// loadFor validates the given variable set against the environment, returning a
// single error that lists every missing or whitespace-only variable.
func loadFor(requiredVars []string) (*Config, error) {
	var missing []string
	c := &Config{}

	for _, name := range requiredVars {
		check(name, configTarget(c, name), &missing)
	}

	if len(missing) > 0 {
		return nil, fmt.Errorf("missing environment variables: %s", strings.Join(missing, ", "))
	}
	return c, nil
}

// configTarget maps a variable name to the Config field it populates, or nil
// when the variable is unknown (kept out of the required/optional lists).
func configTarget(c *Config, name string) *string {
	switch name {
	case "DATABASE_URL":
		return &c.DatabaseURL
	case "OPENAI_API_KEY":
		return &c.OpenAIKey
	case "OPENAI_BASE_URL":
		return &c.OpenAIBaseURL
	case "TELEGRAM_BOT_TOKEN":
		return &c.TelegramBotToken
	case "NOTIFY_SECRET":
		return &c.NotifySecret
	case "JWT_SECRET":
		return &c.JWTSecret
	case "PORT":
		return &c.Port
	default:
		return nil
	}
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
