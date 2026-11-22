// Package extract turns scraped page text into a normalised conference record
// by calling the LLM. It is the Go port of scraper/extraction.
//
// The model is gpt-oss-120b served through an OpenAI-compatible endpoint
// (single API key, no rotation), bounded by a sliding-window RPM limit and a
// daily cap (internal/limiter). Requests are plain HTTP — no SDK — so the wire
// contract matches the Python OpenAI-client calls exactly.
package extract
