package extract

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"confnotifier/internal/limiter"
)

// transientSignals are substrings that mark an error worth retrying on another
// attempt (mirrors scraper/extraction/client/gemini.py _is_transient).
var transientSignals = []string{
	"429", "503", "500", "rate", "unavailable", "overloaded", "timeout", "deadline exceeded",
}

func isTransient(err error) bool {
	s := strings.ToLower(err.Error())
	for _, sig := range transientSignals {
		if strings.Contains(s, sig) {
			return true
		}
	}
	return false
}

// Client is a single OpenAI-compatible endpoint + its rate limiter.
type Client struct {
	baseURL   string
	apiKey    string
	http      *http.Client
	limiter   *limiter.Limiter
	maxTokens int
	attempts  int
	// modelOverride, when non-empty, replaces the package Model const for this
	// client only — used to target a local server whose model id differs.
	modelOverride string
}

// ClientConfig configures a Client.
type ClientConfig struct {
	BaseURL       string
	APIKey        string
	RPM           int
	RPD           int
	Timeout       time.Duration
	MaxTokens     int
	Attempts      int
	ModelOverride string // when set, overrides the package Model const (e.g. a local server's model id)
}

// NewClient builds a Client from config.
func NewClient(cfg ClientConfig) *Client {
	timeout := cfg.Timeout
	if timeout == 0 {
		timeout = 30 * time.Second
	}
	maxTokens := cfg.MaxTokens
	if maxTokens == 0 {
		maxTokens = DefaultMaxTokens
	}
	attempts := cfg.Attempts
	if attempts < 1 {
		attempts = 1
	}
	return &Client{
		baseURL:       strings.TrimRight(cfg.BaseURL, "/"),
		apiKey:        cfg.APIKey,
		http:          &http.Client{Timeout: timeout},
		limiter:       limiter.New(cfg.RPM, cfg.RPD, time.Minute),
		maxTokens:     maxTokens,
		attempts:      attempts,
		modelOverride: cfg.ModelOverride,
	}
}

// DailyCount reports requests used today.
func (c *Client) DailyCount() int { return c.limiter.DailyCount() }

// DailyExhausted reports whether the daily cap is spent.
func (c *Client) DailyExhausted() bool { return c.limiter.DailyExhausted() }

// chatRequest / chatResponse mirror the OpenAI chat-completions wire shape.
type chatRequest struct {
	Model          string          `json:"model"`
	Messages       []chatMessage   `json:"messages"`
	Temperature    float64         `json:"temperature"`
	MaxTokens      int             `json:"max_tokens"`
	ResponseFormat *responseFormat `json:"response_format,omitempty"`
}

type chatMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type responseFormat struct {
	Type       string         `json:"type"`
	JSONSchema *jsonSchemaDef `json:"json_schema,omitempty"`
}

type jsonSchemaDef struct {
	Name   string          `json:"name"`
	Schema json.RawMessage `json:"schema"`
}

type chatResponse struct {
	Choices []struct {
		Message struct {
			Content string `json:"content"`
		} `json:"message"`
	} `json:"choices"`
}

// Complete sends one structured completion and returns the parsed object.
//
// It acquires a limiter slot, POSTs to the OpenAI-compatible endpoint, and
// repairs the reply. On a transient failure it retries up to Attempts times.
func (c *Client) Complete(ctx context.Context, systemPrompt, userContent, schemaJSON string) (map[string]any, error) {
	if err := c.limiter.Acquire(); err != nil {
		return nil, err
	}

	var lastErr error
	for attempt := 1; attempt <= c.attempts; attempt++ {
		payload := chatRequest{
			Model:       c.modelOrConst(),
			Temperature: Temperature,
			MaxTokens:   c.maxTokens,
			Messages: []chatMessage{
				{Role: "system", Content: systemPrompt},
				{Role: "user", Content: userContent},
			},
		}
		if schemaJSON != "" {
			payload.ResponseFormat = &responseFormat{
				Type: "json_schema",
				JSONSchema: &jsonSchemaDef{
					Name:   ResponseSchemaName,
					Schema: json.RawMessage(schemaJSON),
				},
			}
		}
		body, err := json.Marshal(payload)
		if err != nil {
			c.limiter.Release()
			return nil, err
		}

		req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.endpoint(), bytes.NewReader(body))
		if err != nil {
			c.limiter.Release()
			return nil, err
		}
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("Authorization", "Bearer "+c.apiKey)

		resp, err := c.http.Do(req)
		if err != nil {
			lastErr = fmt.Errorf("complete: %w", err)
			if isTransient(lastErr) && attempt < c.attempts {
				continue
			}
			c.limiter.Release()
			return nil, lastErr
		}
		defer resp.Body.Close()
		data, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<22))

		if resp.StatusCode == http.StatusOK {
			var cr chatResponse
			if err := json.Unmarshal(data, &cr); err != nil || len(cr.Choices) == 0 {
				lastErr = fmt.Errorf("complete: bad success body")
				c.limiter.Release()
				return nil, lastErr
			}
			raw := cr.Choices[0].Message.Content
			parsed, err := RepairJSON(raw)
			if err == nil {
				return parsed, nil
			}
			// Unparseable on first attempt: release the slot and retry once.
			lastErr = err
			if attempt == 1 {
				c.limiter.Release()
				continue
			}
			c.limiter.Release()
			return nil, fmt.Errorf("complete: unparseable reply: %w", err)
		}

		// Non-2xx.
		lastErr = fmt.Errorf("complete: HTTP %d: %s", resp.StatusCode, safeTrunc(string(data), 500))
		if isTransient(lastErr) && attempt < c.attempts {
			continue
		}
		c.limiter.Release()
		return nil, lastErr
	}
	return nil, lastErr
}

// modelOrConst returns the override model id, or the package Model const.
func (c *Client) modelOrConst() string {
	if c.modelOverride != "" {
		return c.modelOverride
	}
	return Model
}

// endpoint returns the chat-completions URL.
func (c *Client) endpoint() string {
	url := c.baseURL
	if !strings.HasSuffix(url, "/chat/completions") {
		if !strings.HasSuffix(url, "/v1") {
			url += "/v1"
		}
		url += "/chat/completions"
	}
	return url
}
