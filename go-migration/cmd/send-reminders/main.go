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

	// Notify pending conferences
	pending, err := pool.GetPendingConferencesForNotification(ctx)
	if err != nil {
		slog.Error("get pending conferences failed", "error", err)
		os.Exit(1)
	}
	slog.Info("pending conferences to notify", "count", len(pending))

	for _, conf := range pending {
		if err := telegram.SendNewConference(&conf); err != nil {
			slog.Error("notification failed", "conf_id", conf.ID, "error", err)
			continue
		}
		if err := pool.MarkNotified(ctx, conf.ID); err != nil {
			slog.Error("mark notified failed", "conf_id", conf.ID, "error", err)
		}
	}

	// Deadline reminders
	due, err := pool.GetDeadlinesDue(ctx, cfg.ReminderDaysBefore)
	if err != nil {
		slog.Error("get deadlines failed", "error", err)
		os.Exit(1)
	}
	slog.Info("deadline reminders to send", "count", len(due))

	for _, conf := range due {
		if err := telegram.SendDeadlineReminder(&conf); err != nil {
			slog.Error("reminder failed", "conf_id", conf.ID, "error", err)
		}
	}

	// CertSpotter monitor
	_ = cfg.CertSpotterAPIKey

	slog.Info("send-reminders complete")
}
