# BD Conference Bot — Go + TypeScript Migration

Migrating the Python-based conference tracker to Go (orchestration, HTTP, DB) + TypeScript (Playwright browser agent).

## Architecture

```
Go binary (bd-conf-bot)          stdin/stdout JSON       TypeScript (Bun/Node)
┌─────────────────────────────┐  ─────────────────────→  ┌─────────────────┐
│                             │  {"id":1,"method":       │  browser-agent   │
│  cmd/scraper                │   "fetch_page_text",     │  (Playwright)    │
│  cmd/send-reminders         │   "params":{"url":...}}  │                  │
│  cmd/verify-deadlines       │                          │  • page.goto()   │
│                             │  ←─────────────────────  │  • evaluate()    │
│  internal/                  │  {"id":1,"result":       │  • content()     │
│    browser/ → TS subprocess │   "text": "..."}         │                  │
│    config/  → env loader    │                          └─────────────────┘
│    db/      → pgx pool      │
│    fetcher/ → net/http+goquery│
│    extractor/→ Gemini API   │
│    notifier/→ Telegram API  │
│    sources/ → handlers      │
└─────────────────────────────┘
```

## Prerequisites

- Go 1.23+
- Node.js 20+ or Bun
- PostgreSQL 16+
- Playwright browsers (`npx playwright install chromium`)

## Setup

```bash
# 1. Copy environment
cp .env.example .env
# Edit .env with your credentials

# 2. Install TS dependencies and build
cd ts && npm install && npx playwright install chromium && npx tsc && cd ..

# 3. Install Go dependencies
go mod tidy

# 4. Build everything
make all

# 5. Test
make test
```

## Running

```bash
# Full scraper (homepage scan + special sources + LLM extraction)
make run-scraper

# Send pending notifications + deadline reminders
make run-reminders

# Verify and update deadlines
make run-deadlines

# Development mode (TS agent only, for testing Playwright behavior)
make ts-dev
```

## Environment Variables

See `.env.example` for all required variables.

## Project Structure

```
go-migration/
├── cmd/
│   ├── scraper/            # Main scraper orchestrator
│   ├── send-reminders/     # Notification bot (runs 1x/day)
│   └── verify-deadlines/   # Deadline verifier (runs 1x/day)
├── internal/
│   ├── browser/            # TS subprocess IPC client
│   ├── config/             # Env-based configuration
│   ├── db/                 # PostgreSQL (pgx) layer
│   ├── extractor/          # Gemini LLM extraction
│   ├── fetcher/            # HTTP + goquery HTML parsing
│   ├── notifier/           # Telegram bot API
│   └── sources/            # Homepage scan, special sources, CertSpotter
├── ts/
│   ├── src/
│   │   ├── agent.ts        # Playwright browser agent (stdin/stdout IPC)
│   │   └── protocol.ts     # Request/response type definitions
│   ├── package.json
│   └── tsconfig.json
├── go.mod
├── Makefile
├── .env.example
└── README.md
```
