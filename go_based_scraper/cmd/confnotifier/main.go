// ConfNotifier — Go-based scraper and backend API.
//
// Usage:
//
//	confnotifier <subcommand> [arguments]
//
// Subcommands:
//
//	api                          Start the HTTP API server
//	scrape [--dry-run]           Run the scraper pipeline
//	verify                       Run deadline verification only
//	remind                       Send daily reminders
//	notify <action>              Send notifications (digest, bookmarks, daily)
//	healthcheck                  Start the health-check server
package main

import (
	"context"
	"fmt"
	"log"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"confnotifier/internal/config"
	"confnotifier/internal/discovery"
	"confnotifier/internal/extract"
	"confnotifier/internal/health"
	"confnotifier/internal/httpapi"
	"confnotifier/internal/notify"
	"confnotifier/internal/pipeline"
	"confnotifier/internal/store"
	"confnotifier/internal/verify"
)

func main() {
	if len(os.Args) < 2 {
		printUsage()
		os.Exit(1)
	}

	// Load local .env if present (development convenience; not required in prod).
	loadDotEnv()

	switch os.Args[1] {
	case "healthcheck":
		runHealthcheck()
	case "api":
		runAPI()
	case "scrape":
		runScrape()
	case "verify":
		runVerify()
	case "remind":
		runRemind()
	default:
		fmt.Fprintf(os.Stderr, "unknown subcommand: %s\n", os.Args[1])
		printUsage()
		os.Exit(1)
	}
}

func runHealthcheck() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	srv := health.New(":" + port)
	log.Printf("health server starting on :%s", port)

	// Graceful shutdown on SIGTERM/SIGINT.
	go func() {
		sig := make(chan os.Signal, 1)
		signal.Notify(sig, syscall.SIGTERM, syscall.SIGINT)
		<-sig
		log.Println("shutting down health server...")
		if err := srv.Shutdown(); err != nil {
			log.Fatalf("shutdown error: %v", err)
		}
	}()

	if err := srv.Start(); err != nil {
		log.Fatalf("server error: %v", err)
	}
}

func runAPI() {
	cfg, err := config.Load()
	if err != nil {
		log.Fatalf("config error: %v", err)
	}
	ctx := context.Background()
	p, err := store.NewPool(ctx)
	if err != nil {
		log.Fatalf("db pool: %v", err)
	}
	log.Printf("API starting on :%s", cfg.Port)
	mux := httpapi.NewMux()
	httpapi.RegisterHealth(mux.ServeMux, p)
	httpapi.RegisterConferences(mux.ServeMux, p)
	if err := httpapi.Start(); err != nil {
		log.Fatalf("server error: %v", err)
	}
}

// telegramNotifier adapts notify.HTTPTelegram to pipeline.Notifier.
type telegramNotifier struct{ t *notify.HTTPTelegram }

func (n telegramNotifier) Notify(ctx context.Context, conf map[string]any) (bool, error) {
	body := notify.BuildConferenceMessage(conf)
	if _, err := n.t.SendPlain(ctx, body); err != nil {
		return false, err
	}
	return true, nil
}

func (n telegramNotifier) SendPlain(ctx context.Context, text string) (int, error) {
	return n.t.SendPlain(ctx, text)
}

func runScrape() {
	cfg, err := config.Load()
	if err != nil {
		log.Fatalf("config error: %v", err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	p, err := store.NewPool(ctx)
	if err != nil {
		log.Fatalf("db pool: %v", err)
	}

	client := extract.NewClient(extract.ClientConfig{
		BaseURL:  cfg.OpenAIBaseURL,
		APIKey:   cfg.OpenAIKey,
		RPM:      30,
		RPD:      1000,
		Timeout:  30 * time.Second,
		Attempts: 2,
	})
	log.Printf("extraction client: model=%s base=%s", extract.Model, cfg.OpenAIBaseURL)

	tg := notify.NewHTTPTelegram()
	extractor := extract.NewHTTPExtractor(client)
	disc := discovery.New(p, log.Default())
	runner := pipeline.NewRunner(p, client, disc, extractor, telegramNotifier{tg}, log.Default())
	runner.Run(ctx)
}

func runVerify() {
	cfg, err := config.Load()
	if err != nil {
		log.Fatalf("config error: %v", err)
	}
	ctx := context.Background()
	p, err := store.NewPool(ctx)
	if err != nil {
		log.Fatalf("db pool: %v", err)
	}

	client := extract.NewClient(extract.ClientConfig{
		BaseURL:  cfg.OpenAIBaseURL,
		APIKey:   cfg.OpenAIKey,
		RPM:      30,
		RPD:      1000,
		Timeout:  30 * time.Second,
		Attempts: 2,
	})
	tg := notify.NewHTTPTelegram()
	extractor := extract.NewHTTPExtractor(client)
	v := verify.New(p, extractor, telegramNotifier{tg}, client)
	sent, err := v.Run(ctx)
	if err != nil {
		log.Fatalf("verify: %v", err)
	}
	log.Printf("deadline_verification: complete, %d change notification(s) sent", sent)
}

func runRemind() {
	log.Printf("daily reminders not yet implemented in Go migration")
}

// loadDotEnv reads ./config/.env and exports each key=value pair. It is a
// convenience for local runs; production deployments set real env vars.
func loadDotEnv() {
	for _, path := range []string{"config/.env", ".env"} {
		data, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		for _, line := range splitLines(string(data)) {
			line = trimSpace(line)
			if line == "" || strings.HasPrefix(line, "#") {
				continue
			}
			for i := 0; i < len(line); i++ {
				if line[i] == '=' {
					key := trimSpace(line[:i])
					val := trimSpace(line[i+1:])
					val = stripQuotes(val)
					os.Setenv(key, val)
					break
				}
			}
		}
	}
}

func splitLines(s string) []string {
	var out []string
	cur := ""
	for _, c := range s {
		if c == '\n' {
			out = append(out, cur)
			cur = ""
		} else {
			cur += string(c)
		}
	}
	return append(out, cur)
}

func trimSpace(s string) string {
	start, end := 0, len(s)
	for start < end && (s[start] == ' ' || s[start] == '\t') {
		start++
	}
	for end > start && (s[end-1] == ' ' || s[end-1] == '\t') {
		end--
	}
	return s[start:end]
}

func stripQuotes(s string) string {
	if len(s) >= 2 && s[0] == '"' && s[len(s)-1] == '"' {
		return s[1 : len(s)-1]
	}
	return s
}
