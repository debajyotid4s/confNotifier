package main

import (
	"context"
	"log/slog"
	"os"
	"os/signal"

	"github.com/anomalyco/bd-conf-bot/internal/config"
	"github.com/anomalyco/bd-conf-bot/internal/db"
	"github.com/anomalyco/bd-conf-bot/internal/notifier"
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

	telegram := notifier.NewClient(cfg.TelegramBotToken, cfg.TelegramChatID)
	_ = telegram

	// Check if already ran today
	lastRun, err := pool.TaskLastRun(ctx, "deadline_verification")
	if err == nil && lastRun != nil {
		slog.Info("deadline_verification already ran today", "last_run", lastRun)
		return
	}

	// TODO: Re-fetch conference pages to verify/update deadlines
	// For each conference with upcoming deadlines:
	//   1. Fetch the page again (HTTP or Playwright)
	//   2. Run LLM extraction
	//   3. If deadline changed, update DB and notify

	_ = pool.SetTaskRun(ctx, "deadline_verification")
	slog.Info("verify-deadlines complete")
}
