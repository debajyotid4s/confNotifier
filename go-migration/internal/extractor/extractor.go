package extractor

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	"github.com/anomalyco/bd-conf-bot/internal/models"
)

type Client struct {
	apiKey    string
	model     string
	http      *http.Client
	dailyUsed int
	limit     int
}

func NewClient(apiKey, model string, limit int) *Client {
	return &Client{
		apiKey: apiKey,
		model:  model,
		http:   &http.Client{Timeout: 30 * time.Second},
		limit:  limit,
	}
}

func (c *Client) DailyRemaining() int {
	return c.limit - c.dailyUsed
}

func (c *Client) Extract(ctx context.Context, url, pageText string) (*models.ExtractResult, error) {
	if c.dailyUsed >= c.limit {
		return nil, fmt.Errorf("daily LLM limit reached (%d/%d)", c.dailyUsed, c.limit)
	}

	prompt := fmt.Sprintf(`You are a conference detection assistant. Analyze the following text from a website and determine if it represents an academic conference, workshop, or symposium.

URL: %s

Page text:
%s

Respond with a single JSON object:
{
  "is_conference": true/false,
  "confidence": 0.0-1.0,
  "title": "conference title or empty",
  "date_start": "YYYY-MM-DD or empty",
  "date_end": "YYYY-MM-DD or empty",
  "city": "city or empty",
  "organizer": "organizer or empty",
  "category": "category or empty",
  "deadline": "YYYY-MM-DD or empty",
  "deadline_2": "YYYY-MM-DD or empty",
  "deadline_previous": "YYYY-MM-DD or empty",
  "deadline_2_previous": "YYYY-MM-DD or empty"
}

If is_conference is false, all other fields should be empty strings or false.`, url, pageText)

	payload := map[string]any{
		"model": c.model,
		"messages": []map[string]string{
			{"role": "user", "content": prompt},
		},
		"response_mime_type": "application/json",
	}
	body, _ := json.Marshal(payload)

	req, err := http.NewRequest("POST",
		fmt.Sprintf("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"),
		bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+c.apiKey)

	resp, err := c.http.Do(req)
	if err != nil {
		return nil, fmt.Errorf("gemini api: %w", err)
	}
	defer resp.Body.Close()

	respBody, _ := io.ReadAll(resp.Body)

	var result struct {
		Choices []struct {
			Message struct {
				Content string `json:"content"`
			} `json:"message"`
		} `json:"choices"`
	}
	if err := json.Unmarshal(respBody, &result); err != nil {
		return nil, fmt.Errorf("parse response: %w", err)
	}
	if len(result.Choices) == 0 {
		return nil, fmt.Errorf("no choices in response")
	}

	var extract models.ExtractResult
	if err := json.Unmarshal([]byte(result.Choices[0].Message.Content), &extract); err != nil {
		return nil, fmt.Errorf("parse extract: %w", err)
	}

	c.dailyUsed++
	return &extract, nil
}
