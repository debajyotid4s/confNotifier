// Handler tests for health and conference endpoints.
package httpapi

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestHealthAnonymous(t *testing.T) {
	req := httptest.NewRequest("GET", "/health", nil)
	rr := httptest.NewRecorder()
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{"ok": true})
	})
	middleware(mux).ServeHTTP(rr, req)
	if rr.Code != http.StatusOK {
		t.Errorf("expected 200, got %d", rr.Code)
	}
	var body map[string]any
	if err := json.Unmarshal(rr.Body.Bytes(), &body); err != nil {
		t.Fatalf("invalid JSON: %v", err)
	}
	if _, ok := body["ok"]; !ok {
		t.Error("expected 'ok' key in response")
	}
}

func TestHealthDetailed(t *testing.T) {
	req := httptest.NewRequest("GET", "/health", nil)
	req.Header.Set("X-Notify-Secret", "test-secret")
	rr := httptest.NewRecorder()
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{"ok": true, "db": "ok"})
	})
	middleware(mux).ServeHTTP(rr, req)
	if rr.Code != http.StatusOK {
		t.Errorf("expected 200, got %d", rr.Code)
	}
}

func TestCalendarInvalidMonth(t *testing.T) {
	req := httptest.NewRequest("GET", "/conferences/calendar?month=bad", nil)
	rr := httptest.NewRecorder()
	mux := http.NewServeMux()
	mux.HandleFunc("GET /conferences/calendar", func(w http.ResponseWriter, r *http.Request) {
		month := r.URL.Query().Get("month")
		if !isValidMonth(month) {
			writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "Invalid month"})
			return
		}
	})
	middleware(mux).ServeHTTP(rr, req)
	if rr.Code != http.StatusBadRequest {
		t.Errorf("expected 400, got %d", rr.Code)
	}
}

func TestConferenceNotFound(t *testing.T) {
	req := httptest.NewRequest("GET", "/conferences/999999", nil)
	rr := httptest.NewRecorder()
	mux := http.NewServeMux()
	mux.HandleFunc("GET /conferences/{conf_id}", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusNotFound, map[string]any{"detail": "Not found"})
	})
	middleware(mux).ServeHTTP(rr, req)
	if rr.Code != http.StatusNotFound {
		t.Errorf("expected 404, got %d", rr.Code)
	}
}

func TestSecurityHeaders(t *testing.T) {
	req := httptest.NewRequest("GET", "/health", nil)
	rr := httptest.NewRecorder()
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{"ok": true})
	})
	middleware(mux).ServeHTTP(rr, req)
	if rr.Header().Get("X-Content-Type-Options") != "nosniff" {
		t.Error("missing X-Content-Type-Options header")
	}
	if rr.Header().Get("X-Frame-Options") != "DENY" {
		t.Error("missing X-Frame-Options header")
	}
}

func TestLimitOffsetDefaults(t *testing.T) {
	req := httptest.NewRequest("GET", "/conferences/upcoming", nil)
	limit, offset := limitOffset(req)
	if limit != 30 {
		t.Errorf("expected default limit 30, got %d", limit)
	}
	if offset != 0 {
		t.Errorf("expected default offset 0, got %d", offset)
	}
}

func TestDeadlineStatus(t *testing.T) {
	if deadlineStatus("2030-01-01") != "upcoming" {
		t.Error("expected upcoming for future date")
	}
	if deadlineStatus("2020-01-01") != "past" {
		t.Error("expected past for past date")
	}
	if deadlineStatus("") != "" {
		t.Error("expected empty for empty date")
	}
}
