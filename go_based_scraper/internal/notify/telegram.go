package notify

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"
)

// SendTimeout bounds a single Telegram API call, matching notifier.config.
const sendTimeout = 15 * time.Second

// DefaultTelegramAPI is the production endpoint; overridable in tests.
var DefaultTelegramAPI = "https://api.telegram.org"

// Telegram is the slice of the Telegram Bot API the bot uses. Defined here so
// tests inject a fake and never hit the network.
type Telegram interface {
	// Post sends a method call with a JSON payload and returns the parsed
	// "result" object, or nil on any failure.
	Post(ctx context.Context, method string, payload map[string]any) (map[string]any, error)
	// DeleteMessage deletes a posted message by id.
	DeleteMessage(ctx context.Context, messageID int) error
}

// HTTPTelegram is the production Telegram, talking to api.telegram.org.
type HTTPTelegram struct {
	botToken string
	channel  string
	baseURL  string
	client   *http.Client
}

var _ Telegram = (*HTTPTelegram)(nil)

// NewHTTPTelegram builds a Telegram from the process environment.
func NewHTTPTelegram() *HTTPTelegram {
	return &HTTPTelegram{
		botToken: os.Getenv("TELEGRAM_BOT_TOKEN"),
		channel:  resolveChannel(os.Getenv("TELEGRAM_CHANNEL_ID"), os.Getenv("TELEGRAM_CHANNEL_LINK")),
		baseURL:  DefaultTelegramAPI,
		client:   &http.Client{Timeout: sendTimeout},
	}
}

// NewTestHTTPTelegram builds a Telegram pointed at baseURL (for tests).
func NewTestHTTPTelegram(baseURL, token, channel string) *HTTPTelegram {
	return &HTTPTelegram{
		botToken: token,
		channel:  channel,
		baseURL:  strings.TrimRight(baseURL, "/"),
		client:   &http.Client{Timeout: sendTimeout},
	}
}

func resolveChannel(a, b string) string {
	if strings.Contains(a, "t.me/") {
		return "@" + strings.Trim(strings.SplitN(a, "t.me/", 2)[1], "/")
	}
	if a != "" {
		return a
	}
	return b
}

// TelegramURL returns the API endpoint for a method, for testability.
func (t *HTTPTelegram) telegramURL(method string) string {
	return fmt.Sprintf("%s/bot%s/%s", t.baseURL, t.botToken, method)
}

func (t *HTTPTelegram) Post(ctx context.Context, method string, payload map[string]any) (map[string]any, error) {
	if t.botToken == "" {
		return nil, fmt.Errorf("TELEGRAM_BOT_TOKEN not set")
	}
	body, err := json.Marshal(payload)
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, t.telegramURL(method), bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := t.client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return nil, err
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("telegram %s: %d: %s", method, resp.StatusCode,
			strings.TrimSpace(string(data)[:min(300, len(data))]))
	}
	var out struct {
		OK     bool           `json:"ok"`
		Result map[string]any `json:"result"`
	}
	if err := json.Unmarshal(data, &out); err != nil {
		return nil, err
	}
	return out.Result, nil
}

// SendPlain posts an HTML message to the channel, returning the message id or 0.
func (t *HTTPTelegram) SendPlain(ctx context.Context, text string) (int, error) {
	if t.channel == "" {
		return 0, fmt.Errorf("TELEGRAM_CHANNEL_ID or TELEGRAM_CHANNEL_LINK not set")
	}
	result, err := t.Post(ctx, "sendMessage", map[string]any{
		"chat_id":                  t.channel,
		"text":                     text,
		"parse_mode":               "HTML",
		"disable_web_page_preview": true,
	})
	if err != nil || result == nil {
		return 0, err
	}
	id, _ := result["message_id"].(float64)
	return int(id), nil
}

// DeleteMessage deletes a previously posted message.
func (t *HTTPTelegram) DeleteMessage(ctx context.Context, messageID int) error {
	if t.channel == "" || messageID == 0 {
		return fmt.Errorf("no channel or message id")
	}
	_, err := t.Post(ctx, "deleteMessage", map[string]any{
		"chat_id":    t.channel,
		"message_id": messageID,
	})
	return err
}
