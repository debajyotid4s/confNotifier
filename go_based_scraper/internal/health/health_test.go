package health

import (
	"net/http"
	"testing"
	"time"
)

func TestHealthEndpoint(t *testing.T) {
	s := New("localhost:0") // port 0 = OS picks a free port

	done := make(chan error, 1)
	go func() {
		done <- s.Start()
	}()

	// Give the server a moment to start and pick a port.
	time.Sleep(50 * time.Millisecond)

	addr := s.Addr()
	if addr == "" {
		t.Fatal("server address not set after Start")
	}

	resp, err := http.Get("http://" + addr + "/health")
	if err != nil {
		t.Fatalf("GET /health: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Errorf("status = %d, want %d", resp.StatusCode, http.StatusOK)
	}

	if ct := resp.Header.Get("Content-Type"); ct != "application/json" {
		t.Errorf("Content-Type = %q, want %q", ct, "application/json")
	}
}
