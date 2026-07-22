package sources

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"os"
	"regexp"
	"strings"
	"time"

	"github.com/PuerkitoBio/goquery"

	"github.com/anomalyco/bd-conf-bot/internal/db"
	"github.com/anomalyco/bd-conf-bot/internal/fetcher"
)

type SpecialSource struct {
	Type          string   `json:"type"`
	BaseURL       string   `json:"base_url,omitempty"`
	BaseDomain    string   `json:"base_domain,omitempty"`
	KnownPrefixes []string `json:"known_prefixes,omitempty"`
	ProbeYears    []int    `json:"probe_years,omitempty"`
	Paths         []string `json:"paths,omitempty"`
	URL           string   `json:"url,omitempty"`
}

func LoadSpecialSources(path string) ([]SpecialSource, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()

	body, err := io.ReadAll(f)
	if err != nil {
		return nil, err
	}

	var sources []SpecialSource
	if err := json.Unmarshal(body, &sources); err != nil {
		return nil, err
	}
	return sources, nil
}

func RunSpecialSources(ctx context.Context, dbPool *db.Pool, sources []SpecialSource) ([]string, error) {
	var candidates []string

	for _, src := range sources {
		var urls []string
		switch src.Type {
		case "path":
			urls = handlePath(ctx, dbPool, src)
		case "root_year":
			urls = handleRootYear(ctx, dbPool, src)
		case "subdomain_probe":
			urls = handleSubdomainProbe(ctx, dbPool, src)
		case "conf_info_bd":
			urls = handleConfInfoBD(ctx, dbPool, src)
		default:
			slog.Warn("unknown special source type", "type", src.Type)
		}
		candidates = append(candidates, urls...)
	}

	return candidates, nil
}

func handlePath(ctx context.Context, pool *db.Pool, src SpecialSource) []string {
	baseURL := strings.TrimRight(src.BaseURL, "/")
	year := time.Now().Year()
	probeYears := src.ProbeYears
	if len(probeYears) == 0 {
		probeYears = []int{year, year + 1}
	}

	var candidates []string
	for _, y := range probeYears {
		if len(src.Paths) > 0 {
			for _, tmpl := range src.Paths {
				probeURL := baseURL + strings.ReplaceAll(tmpl, "{year}", fmt.Sprintf("%d", y))
				seen, _ := pool.IsLinkSeen(ctx, probeURL)
				if seen {
					continue
				}
				text, err := fetcher.FetchPageText(probeURL)
				if err != nil || len(text) < 500 {
					continue
				}
				_ = pool.SaveSeenLink(ctx, probeURL, "special")
				candidates = append(candidates, probeURL)
			}
		} else {
			patterns := []string{
				fmt.Sprintf("%s/%d/home/", baseURL, y),
				fmt.Sprintf("%s/%d/", baseURL, y),
			}
			for _, candidate := range patterns {
				seen, _ := pool.IsLinkSeen(ctx, candidate)
				if seen {
					break
				}
				text, err := fetcher.FetchPageText(candidate)
				if err != nil || len(text) < 500 {
					continue
				}
				_ = pool.SaveSeenLink(ctx, candidate, "special")
				candidates = append(candidates, candidate)
				break
			}
		}
	}
	return candidates
}

func handleRootYear(ctx context.Context, pool *db.Pool, src SpecialSource) []string {
	baseURL := src.BaseURL
	text, err := fetcher.FetchPageText(baseURL)
	if err != nil || len(text) < 500 {
		return nil
	}

	doc, err := goquery.NewDocumentFromReader(strings.NewReader(text))
	if err != nil {
		return nil
	}

	searchText, _ := doc.Find("title").Html()
	if searchText == "" {
		searchText, _ = doc.Find("h1").Html()
	}
	if searchText == "" {
		searchText = doc.Text()
		if len(searchText) > 2000 {
			searchText = searchText[:2000]
		}
	}

	year := time.Now().Year()
	re := regexp.MustCompile(`\b(\d{4})\b`)
	for _, match := range re.FindAllStringSubmatch(searchText, -1) {
		candidateYear := parseInt(match[1])
		if candidateYear >= year && candidateYear <= year+2 {
			exists, _ := pool.IsEditionInDB(ctx, baseURL, candidateYear)
			if exists {
				slog.Info("edition already in DB, skipping", "url", baseURL, "year", candidateYear)
				return nil
			}
			candidate := fmt.Sprintf("root_year:%d:%s", candidateYear, baseURL)
			_ = pool.SaveSeenLink(ctx, candidate, "special")
			return []string{candidate}
		}
	}

	return nil
}

func handleSubdomainProbe(ctx context.Context, pool *db.Pool, src SpecialSource) []string {
	var candidates []string
	httpClient := &http.Client{Timeout: 10 * time.Second}

	for _, prefix := range src.KnownPrefixes {
		for _, year := range src.ProbeYears {
			probeURL := fmt.Sprintf("https://%s%d.%s", prefix, year, src.BaseDomain)
			seen, _ := pool.IsLinkSeen(ctx, probeURL)
			if seen {
				continue
			}
			resp, err := httpClient.Get(probeURL)
			if err == nil && resp.StatusCode == 200 {
				resp.Body.Close()
				_ = pool.SaveSeenLink(ctx, probeURL, "special")
				candidates = append(candidates, probeURL)
			}
		}
		// Also probe bare prefix (no year)
		probeURL := fmt.Sprintf("https://%s.%s", prefix, src.BaseDomain)
		seen, _ := pool.IsLinkSeen(ctx, probeURL)
		if !seen {
			resp, err := httpClient.Get(probeURL)
			if err == nil && resp.StatusCode == 200 {
				resp.Body.Close()
				_ = pool.SaveSeenLink(ctx, probeURL, "special")
				candidates = append(candidates, probeURL)
			}
		}
	}
	return candidates
}

func handleConfInfoBD(ctx context.Context, pool *db.Pool, src SpecialSource) []string {
	url := src.URL
	if url == "" {
		url = "https://conf.info.bd"
	}

	resp, err := http.Get(url)
	if err != nil {
		return nil
	}
	defer resp.Body.Close()

	doc, err := goquery.NewDocumentFromReader(resp.Body)
	if err != nil {
		return nil
	}

	var candidates []string
	doc.Find("a.conf-link").Each(func(i int, s *goquery.Selection) {
		href, exists := s.Attr("href")
		if !exists || href == "" {
			return
		}
		seen, _ := pool.IsLinkSeen(ctx, href)
		if seen {
			return
		}
		_ = pool.SaveSeenLink(ctx, href, "special")
		candidates = append(candidates, href)
	})

	return candidates
}

func parseInt(s string) int {
	var n int
	fmt.Sscanf(s, "%d", &n)
	return n
}
