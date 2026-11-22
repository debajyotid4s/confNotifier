package notify

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"
)

// fakeTelegram records calls and returns a canned result.
type fakeTelegram struct {
	mu      sync.Mutex
	calls   []string
	result  map[string]any
	postErr error
}

func (f *fakeTelegram) Post(_ context.Context, method string, _ map[string]any) (map[string]any, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.calls = append(f.calls, method)
	return f.result, f.postErr
}

func (f *fakeTelegram) DeleteMessage(_ context.Context, _ int) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.calls = append(f.calls, "deleteMessage")
	return nil
}

func (f *fakeTelegram) methods() []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]string(nil), f.calls...)
}

func TestSendPlainSuccess(t *testing.T) {
	f := &fakeTelegram{result: map[string]any{"message_id": float64(99)}}
	if _, err := f.Post(context.Background(), "sendMessage", map[string]any{"text": "hi"}); err != nil {
		t.Fatalf("Post error: %v", err)
	}
	got := f.methods()
	if len(got) != 1 || got[0] != "sendMessage" {
		t.Errorf("expected sendMessage, got %v", got)
	}
}

func TestSendPlainID(t *testing.T) {
	f := &fakeTelegram{result: map[string]any{"message_id": float64(5)}}
	id, err := f.Post(context.Background(), "sendMessage", map[string]any{"text": "hi"})
	if err != nil {
		t.Fatalf("Post error: %v", err)
	}
	if id["message_id"].(float64) != 5 {
		t.Errorf("expected 5, got %v", id["message_id"])
	}
}

func TestSendPlainNoChannel(t *testing.T) {
	tg := NewTestHTTPTelegram("http://localhost", "tok", "")
	if _, err := tg.SendPlain(context.Background(), "hi"); err == nil {
		t.Error("expected error when channel unset")
	}
}

func TestDeleteMessageNoChannel(t *testing.T) {
	tg := NewTestHTTPTelegram("http://localhost", "tok", "")
	if err := tg.DeleteMessage(context.Background(), 5); err == nil {
		t.Error("expected error when channel unset")
	}
}

func TestHTTPPostSuccess(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		io.WriteString(w, `{"ok":true,"result":{"message_id":42}}`)
	}))
	defer srv.Close()

	tg := NewTestHTTPTelegram(srv.URL, "tok", "@chan")
	result, err := tg.Post(context.Background(), "sendMessage", map[string]any{"chat_id": "@chan", "text": "hi"})
	if err != nil {
		t.Fatalf("Post error: %v", err)
	}
	if result["message_id"].(float64) != 42 {
		t.Errorf("expected 42, got %v", result["message_id"])
	}
}

func TestHTTPPostErrorStatus(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusBadRequest)
		io.WriteString(w, `{"ok":false,"description":"Bad Request"}`)
	}))
	defer srv.Close()

	tg := NewTestHTTPTelegram(srv.URL, "tok", "@chan")
	if _, err := tg.Post(context.Background(), "sendMessage", map[string]any{"text": "hi"}); err == nil {
		t.Error("expected error on non-200")
	}
}

func TestHTTPPostTimeout(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		// Hold the connection open past the client timeout.
		time.Sleep(2 * time.Second)
	}))
	defer srv.Close()

	tg := NewTestHTTPTelegram(srv.URL, "tok", "@chan")
	tg.client.Timeout = 50 * time.Millisecond
	if _, err := tg.Post(context.Background(), "sendMessage", map[string]any{"text": "hi"}); err == nil {
		t.Error("expected timeout error")
	}
}

func TestResolveChannel(t *testing.T) {
	cases := map[string]string{
		"@handle":             "@handle",
		"":                    "",
		"12345":               "12345",
		"https://t.me/mychan": "@mychan",
		"t.me/mychan":         "@mychan",
	}
	for in, want := range cases {
		if got := resolveChannel(in, ""); got != want {
			t.Errorf("resolveChannel(%q) = %q, want %q", in, got, want)
		}
	}
}
