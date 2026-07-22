package main

import (
	"context"
	"log/slog"
	"os"
	"os/signal"

	"github.com/anomalyco/bd-conf-bot/internal/browser"
	"github.com/anomalyco/bd-conf-bot/internal/config"
	"github.com/anomalyco/bd-conf-bot/internal/db"
	"github.com/anomalyco/bd-conf-bot/internal/extractor"
	"github.com/anomalyco/bd-conf-bot/internal/notifier"
	"github.com/anomalyco/bd-conf-bot/internal/sources"
)

func main() {
	slog.SetDefault(slog.New(slog.NewTextHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo})))

	cfg, err := config.Load()
	if err != nil {
		slog.Error("config load failed", "error", err)
		os.Exit(1)
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Handle shutdown
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, os.Interrupt)
	go func() {
		<-sigCh
		cancel()
	}()

	pool, err := db.Connect(ctx, cfg.DatabaseURL)
	if err != nil {
		slog.Error("db connect failed", "error", err)
		os.Exit(1)
	}
	defer pool.Close()

	browserAgent, err := browser.NewAgent(ctx, cfg.PlaywrightPath+"/dist/agent.js")
	if err != nil {
		slog.Warn("browser agent unavailable, continuing without JS rendering", "error", err)
	}
	if browserAgent != nil {
		defer browserAgent.Close()
	}

	llmClient := extractor.NewClient(cfg.GeminiAPIKey, cfg.GeminiModel, cfg.LLMDailyLimit)
	telegram := notifier.NewClient(cfg.TelegramBotToken, cfg.TelegramChatID)

	slog.Info("BD Conference Bot — scraper started")

	// Phase 1: Load universities
	domains, err := sources.LoadUniversities("") // TODO: load from config/universities.json
	if err != nil {
		slog.Warn("could not load universities, using empty list", "error", err)
		domains = nil
	}

	// Phase 2: Scan homepages
	candidates, err := sources.ScanHomepages(ctx, pool, domains, browserAgent)
	if err != nil {
		slog.Error("homepage scanning failed", "error", err)
	}
	slog.Info("homepage scan complete", "candidates", len(candidates))

	// Phase 3: Special sources
	specialSources, err := sources.LoadSpecialSources("config/special_sources.json")
	if err != nil {
		slog.Warn("could not load special sources", "error", err)
	}
	specialCandidates, err := sources.RunSpecialSources(ctx, pool, specialSources)
	if err != nil {
		slog.Error("special sources failed", "error", err)
	}
	slog.Info("special sources complete", "candidates", len(specialCandidates))

	allCandidates := append(candidates, specialCandidates...)
	// TODO: re-queue pending URLs from previous runs

	slog.Info("processing candidates", "count", len(allCandidates))

	// Phase 4: Extract & save conferences
	for _, candidate := range allCandidates {
		// Fetch page text (browser agent if available, else HTTP)
		// Call LLM extractor
		// Save to DB if conference
		// Notify if inserted
		_ = llmClient
		_ = telegram
		_ = candidate
	}

	slog.Info("scraper run complete")
}
