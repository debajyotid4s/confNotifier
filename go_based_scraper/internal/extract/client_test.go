package extract

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestCompleteSuccess(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/chat/completions" {
			t.Errorf("path = %q", r.URL.Path)
		}
		if r.Header.Get("Authorization") != "Bearer test-key" {
			t.Errorf("auth = %q", r.Header.Get("Authorization"))
		}
		var req chatRequest
		json.NewDecoder(r.Body).Decode(&req)
		if req.Model != Model {
			t.Errorf("model = %q", req.Model)
		}
		if req.ResponseFormat == nil || req.ResponseFormat.Type != "json_schema" {
			t.Error("expected json_schema response_format")
		}
		w.WriteHeader(http.StatusOK)
		io.WriteString(w, `{"choices":[{"message":{"content":"{\"is_conference\":true,\"title\":\"X\"}"}}]}`)
	}))
	defer srv.Close()

	c := NewClient(ClientConfig{BaseURL: srv.URL, APIKey: "test-key", RPM: 30, RPD: 1000})
	out, err := c.Complete(context.Background(), SystemPrompt, "page", ExtractionSchemaJSON)
	if err != nil {
		t.Fatalf("complete: %v", err)
	}
	if out["is_conference"].(bool) != true {
		t.Errorf("is_conference = %v", out["is_conference"])
	}
}

func TestCompleteTransientRetries(t *testing.T) {
	var calls int
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		if calls == 1 {
			w.WriteHeader(http.StatusTooManyRequests)
			io.WriteString(w, "429 rate limited")
			return
		}
		w.WriteHeader(http.StatusOK)
		io.WriteString(w, `{"choices":[{"message":{"content":"{\"ok\":1}"}}]}`)
	}))
	defer srv.Close()

	c := NewClient(ClientConfig{BaseURL: srv.URL, APIKey: "k", RPM: 30, RPD: 1000, Attempts: 3})
	out, err := c.Complete(context.Background(), SystemPrompt, "page", ExtractionSchemaJSON)
	if err != nil {
		t.Fatalf("complete after retry: %v", err)
	}
	if out["ok"].(float64) != 1 {
		t.Errorf("ok = %v", out["ok"])
	}
	if calls < 2 {
		t.Errorf("expected retry, calls = %d", calls)
	}
}

func TestCompleteDailyCap(t *testing.T) {
	calls := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		calls++
		w.WriteHeader(http.StatusOK)
		io.WriteString(w, `{"choices":[{"message":{"content":"{}"}}]}`)
	}))
	defer srv.Close()

	c := NewClient(ClientConfig{BaseURL: srv.URL, APIKey: "k", RPM: 30, RPD: 2})
	for i := 0; i < 2; i++ {
		if _, err := c.Complete(context.Background(), SystemPrompt, "p", ExtractionSchemaJSON); err != nil {
			t.Fatalf("complete %d: %v", i, err)
		}
	}
	if _, err := c.Complete(context.Background(), SystemPrompt, "p", ExtractionSchemaJSON); err == nil {
		t.Error("expected daily cap error")
	}
	if !c.DailyExhausted() {
		t.Error("expected DailyExhausted")
	}
}

func TestEndpointNormalisation(t *testing.T) {
	c := NewClient(ClientConfig{BaseURL: "https://x.openai.com/", APIKey: "k", RPM: 1, RPD: 1})
	if got := c.endpoint(); got != "https://x.openai.com/v1/chat/completions" {
		t.Errorf("endpoint = %q", got)
	}
	c2 := NewClient(ClientConfig{BaseURL: "https://x.openai.com/v1", APIKey: "k", RPM: 1, RPD: 1})
	if got := c2.endpoint(); got != "https://x.openai.com/v1/chat/completions" {
		t.Errorf("endpoint2 = %q", got)
	}
}
