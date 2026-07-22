package config

import (
	"fmt"
	"os"
	"strconv"
)

type Config struct {
	DatabaseURL        string
	GeminiAPIKey       string
	GeminiModel        string
	TelegramBotToken   string
	TelegramChatID     string
	CertSpotterAPIKey  string
	PlaywrightPath     string
	LLMDailyLimit      int
	ReminderDaysBefore int
}

func Load() (*Config, error) {
	cfg := &Config{
		DatabaseURL:        envOrDefault("DATABASE_URL", "postgres://localhost:5432/bd_conf_bot"),
		GeminiAPIKey:       os.Getenv("GEMINI_API_KEY"),
		GeminiModel:        envOrDefault("GEMINI_MODEL", "gemini-2.0-flash"),
		TelegramBotToken:   os.Getenv("TELEGRAM_BOT_TOKEN"),
		TelegramChatID:     os.Getenv("TELEGRAM_CHAT_ID"),
		CertSpotterAPIKey:  os.Getenv("CERTSPOTTER_API_KEY"),
		PlaywrightPath:     envOrDefault("PLAYWRIGHT_PATH", "node"),
		LLMDailyLimit:      envOrDefaultInt("LLM_DAILY_LIMIT", 20),
		ReminderDaysBefore: envOrDefaultInt("REMINDER_DAYS_BEFORE", 7),
	}

	if cfg.GeminiAPIKey == "" {
		return nil, fmt.Errorf("GEMINI_API_KEY is required")
	}
	if cfg.TelegramBotToken == "" {
		return nil, fmt.Errorf("TELEGRAM_BOT_TOKEN is required")
	}

	return cfg, nil
}

func envOrDefault(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func envOrDefaultInt(key string, def int) int {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return def
}
