// Package main provides usage help for the confnotifier CLI.
package main

import (
	"io"
	"os"
)

const usageText = `Usage: confnotifier <subcommand>

Subcommands:
  api                          Start the HTTP API server
  scrape [--dry-run]           Run the scraper pipeline
  verify                       Run deadline verification only
  remind                       Send daily reminders
  notify <action>              Send notifications
  healthcheck                  Start the health-check server`

func printUsage() {
	io.WriteString(os.Stderr, usageText+"\n")
}
