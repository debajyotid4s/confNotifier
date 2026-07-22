package notifier

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	"github.com/anomalyco/bd-conf-bot/internal/models"
)

type Client struct {
	botToken string
	chatID   string
	http     *http.Client
}

func NewClient(botToken, chatID string) *Client {
	return &Client{
		botToken: botToken,
		chatID:   chatID,
		http:     &http.Client{Timeout: 15 * time.Second},
	}
}

func (c *Client) SendNewConference(conf *models.Conference) error {
	text := fmt.Sprintf(
		"*New Conference Detected*\n\n"+
			"*%s*\n"+
			"📅 %s – %s\n"+
			"📍 %s, %s\n"+
			"🌐 %s\n",
		conf.Title,
		formatDate(conf.DateStart), formatDate(conf.DateEnd),
		nullable(conf.City), conf.Country,
		conf.Website,
	)
	return c.sendMessage(text)
}

func (c *Client) SendDeadlineReminder(conf *models.Conference) error {
	text := fmt.Sprintf(
		"*Deadline Reminder*\n\n"+
			"*%s*\n"+
			"📅 *%s* — %s\n"+
			"🌐 %s\n",
		conf.Title,
		nullable(conf.SubmissionDeadlineLabel),
		formatDate(conf.SubmissionDeadline),
		conf.Website,
	)
	return c.sendMessage(text)
}

func (c *Client) sendMessage(text string) error {
	payload := map[string]any{
		"chat_id":    c.chatID,
		"text":       text,
		"parse_mode": "Markdown",
	}
	body, _ := json.Marshal(payload)

	resp, err := c.http.Post(
		fmt.Sprintf("https://api.telegram.org/bot%s/sendMessage", c.botToken),
		"application/json",
		bytes.NewReader(body),
	)
	if err != nil {
		return fmt.Errorf("telegram api: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		respBody, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("telegram API %d: %s", resp.StatusCode, string(respBody))
	}
	return nil
}

func formatDate(t *time.Time) string {
	if t == nil {
		return "TBA"
	}
	return t.Format("Jan 2, 2006")
}

func nullable(s *string) string {
	if s == nil {
		return "TBA"
	}
	return *s
}
