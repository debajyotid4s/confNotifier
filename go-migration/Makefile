.PHONY: all build clean test run-scraper run-reminders run-deadlines ts-setup ts-build ts-dev

GO ?= go
BUN ?= bun
NPM ?= npm

all: ts-build build

# ── Go ──────────────────────────────────────────────────

build:
	$(GO) build ./cmd/scraper
	$(GO) build ./cmd/send-reminders
	$(GO) build ./cmd/verify-deadlines
	@echo "Binaries: scraper, send-reminders, verify-deadlines"

test:
	$(GO) test ./...

clean:
	rm -f scraper send-reminders verify-deadlines
	rm -rf ts/dist

# ── TypeScript ──────────────────────────────────────────

ts-setup:
	cd ts && $(NPM) install
	cd ts && npx playwright install chromium

ts-build:
	cd ts && npx tsc

ts-dev:
	cd ts && npx tsx src/agent.ts

# ── Run ─────────────────────────────────────────────────

run-scraper: ts-build build
	./scraper

run-reminders: build
	./send-reminders

run-deadlines: ts-build build
	./verify-deadlines

# ── Development ─────────────────────────────────────────

dev: ts-build build
	@echo "Build complete. Use run-scraper, run-reminders, or run-deadlines"
