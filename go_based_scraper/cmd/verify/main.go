// Command verify fetches every discovery source's live URL(s) and runs LLM
// extraction on each, logging reachability and verdicts to verify_report.log.
// It performs no database writes — a reachability + extraction smoke test.
//
// Reachability uses a plain HTTP GET. Extraction runs against Groq first; when
// Groq returns HTTP 429 (rate limit) it falls back to the local llama-server.
// Extraction is serial because Groq's free tier is a single low-TPM endpoint.
package main

import (
	"context"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strings"
	"time"

	"confnotifier/internal/discovery"
	"confnotifier/internal/extract"
)

func loadEnv() {
	for _, path := range []string{"config/.env", ".env"} {
		data, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		for _, line := range strings.Split(string(data), "\n") {
			line = strings.TrimSpace(line)
			if line == "" || strings.HasPrefix(line, "#") {
				continue
			}
			for i := 0; i < len(line); i++ {
				if line[i] == '=' {
					os.Setenv(strings.TrimSpace(line[:i]), strings.TrimSpace(line[i+1:]))
					break
				}
			}
		}
	}
}

// candidateURLs returns the live URL(s) to check for one source. Regular
// sources check their single homepage; special sources check their base_url
// (the year-templated probes are covered by the real discovery runner).
func candidateURLs(s discovery.Source) []string {
	if s.BaseURL == "" {
		return nil
	}
	u := s.BaseURL
	if s.Type == "conf_info_bd" && u == "" {
		u = "https://conf.info.bd"
	}
	return []string{strings.TrimSuffix(u, "/")}
}

func main() {
	loadEnv()
	log.SetFlags(log.LstdFlags)

	groq := extract.NewClient(extract.ClientConfig{
		BaseURL:  os.Getenv("OPENAI_BASE_URL"),
		APIKey:   os.Getenv("OPENAI_API_KEY"),
		RPM:      30,
		RPD:      1000,
		Timeout:  30 * time.Second,
		Attempts: 2,
	})
	local := extract.NewClient(extract.ClientConfig{
		BaseURL:       os.Getenv("LOCAL_LLM_BASE_URL"),
		APIKey:        "not-needed",
		RPM:           60,
		RPD:           10000,
		Timeout:       120 * time.Second,
		Attempts:      1,
		ModelOverride: "ornith-1.5-35b-a3b-iq4-xs",
	})
	httpClient := &http.Client{Timeout: 20 * time.Second}
	ua := "confNotifier-verify/1.0 (+https://github.com/confnotifier)"

	var jobs []struct{ source, url string }
	for _, s := range sources() {
		for _, u := range candidateURLs(s) {
			jobs = append(jobs, struct{ source, url string }{s.Type, u})
		}
	}

	out, err := os.Create("verify_report.log")
	if err != nil {
		log.Fatalf("create report: %v", err)
	}
	defer out.Close()
	log.SetOutput(out)

	fmt.Fprintf(out, "=== confNotifier verify run %s ===\n", time.Now().Format(time.RFC3339))
	fmt.Fprintf(out, "sources loaded: %d  candidate URLs: %d\n", len(sources()), len(jobs))
	log.Printf("reachability: plain HTTP GET (20s). Extraction: Groq first, local fallback on 429")
	log.Printf("")

	fetchText := func(url string) (string, error) {
		req, err := http.NewRequestWithContext(context.Background(), http.MethodGet, url, nil)
		if err != nil {
			return "", err
		}
		req.Header.Set("User-Agent", ua)
		resp, err := httpClient.Do(req)
		if err != nil {
			return "", err
		}
		defer resp.Body.Close()
		if resp.StatusCode != http.StatusOK {
			return "", fmt.Errorf("HTTP %d", resp.StatusCode)
		}
		data, _ := io.ReadAll(io.LimitReader(resp.Body, 5<<20))
		return strings.TrimSpace(string(data)), nil
	}

	reachable, unreachable, extracted, fallbacks := 0, 0, 0, 0
	ctx := context.Background()
	groqExt := extract.NewHTTPExtractor(groq)
	localExt := extract.NewHTTPExtractor(local)

	for _, j := range jobs {
		body, err := fetchText(j.url)
		if err != nil || len(body) < 200 {
			unreachable++
			reason := err.Error()
			if err == nil {
				reason = "body too short (" + fmt.Sprintf("%d", len(body)) + " chars)"
			}
			log.Printf("[UNREACHABLE] %-14s %s  (%s)", j.source, j.url, reason)
			continue
		}
		reachable++

		res, err := groqExt.ExtractConferences(ctx, body, j.url, nil, time.Now(), groq)
		if err != nil && strings.Contains(err.Error(), "429") {
			fallbacks++
			log.Printf("[FALLBACK]   %-14s %s  (Groq 429 -> local LLM)", j.source, j.url)
			res, err = localExt.ExtractConferences(ctx, body, j.url, nil, time.Now(), local)
		}
		if err != nil {
			extracted++
			log.Printf("[ERROR]      %-14s %s  (%v)", j.source, j.url, err)
			continue
		}
		if res == nil {
			log.Printf("[NOISE]      %-14s %s  (no conference signal)", j.source, j.url)
			continue
		}
		extracted++
		isConf, _ := res["is_conference"].(bool)
		title, _ := res["title"].(string)
		conf, _ := res["confidence"].(float64)
		tag := "NOT CONF"
		if isConf {
			tag = "CONFERENCE"
		}
		log.Printf("[%s]       %-14s %s  -> %q (conf %.2f)", tag, j.source, j.url, title, conf)
	}

	fmt.Fprintf(out, "\n=== summary ===\n")
	fmt.Fprintf(out, "reachable:      %d\n", reachable)
	fmt.Fprintf(out, "unreachable:    %d\n", unreachable)
	fmt.Fprintf(out, "llm-extracted:  %d\n", extracted)
	fmt.Fprintf(out, "local-fallback: %d\n", fallbacks)
	log.Printf("")
	log.Printf("DONE. reachable=%d unreachable=%d llm-extracted=%d local-fallback=%d", reachable, unreachable, extracted, fallbacks)
}

func sources() []discovery.Source { return discovery.LoadSources("") }
