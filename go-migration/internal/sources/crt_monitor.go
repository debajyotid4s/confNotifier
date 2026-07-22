package sources

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"time"
)

type CertSpotterClient struct {
	apiKey string
	http   *http.Client
}

func NewCertSpotterClient(apiKey string) *CertSpotterClient {
	return &CertSpotterClient{
		apiKey: apiKey,
		http:   &http.Client{Timeout: 30 * time.Second},
	}
}

type CertSpotterEntry struct {
	ID      int64    `json:"id"`
	DNS     []string `json:"dns_names"`
	Issuer  string   `json:"issuer"`
	NotBefore string `json:"not_before"`
}

func (c *CertSpotterClient) GetCertificates(ctx context.Context, domain string, afterID int64) ([]CertSpotterEntry, error) {
	url := fmt.Sprintf("https://api.certspotter.com/v1/issuances?domain=%s&include_subdomains=true&after_id=%d&expand=dns_names",
		domain, afterID)
	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+c.apiKey)

	resp, err := c.http.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}

	var entries []CertSpotterEntry
	if err := json.Unmarshal(body, &entries); err != nil {
		return nil, fmt.Errorf("parse certspotter response: %w", err)
	}

	return entries, nil
}

func (c *CertSpotterClient) ExtractConferenceDomains(entries []CertSpotterEntry) []string {
	var domains []string
	for _, entry := range entries {
		for _, dns := range entry.DNS {
			// Filter for subdomains that look like conferences
			if matchesConferencePattern(dns) {
				domains = append(domains, dns)
			}
		}
	}
	return domains
}

func matchesConferencePattern(domain string) bool {
	// Look for conference-like subdomains: ic*, conf*, workshop*, etc.
	for _, prefix := range []string{"ic", "conf", "workshop", "symposium"} {
		if len(domain) > len(prefix)+1 && domain[:len(prefix)] == prefix && domain[len(prefix)] >= 'a' && domain[len(prefix)] <= 'z' {
			return true
		}
	}
	return false
}

func (c *CertSpotterClient) MonitorNewCertificates(ctx context.Context, domains []string) {
	for _, domain := range domains {
		// TODO: load cursor from DB
		entries, err := c.GetCertificates(ctx, domain, 0)
		if err != nil {
			slog.Warn("certspotter query failed", "domain", domain, "error", err)
			continue
		}
		conferenceDomains := c.ExtractConferenceDomains(entries)
		slog.Info("certspotter results", "domain", domain, "new_conference_domains", len(conferenceDomains))
		// TODO: save candidates and update cursor
	}
}
