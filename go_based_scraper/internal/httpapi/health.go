// /health endpoint.
package httpapi

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"

	"confnotifier/internal/store"
)

// RegisterHealth registers the /health endpoint.
func RegisterHealth(mux *http.ServeMux, p *store.Pool) {
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		secret := os.Getenv("NOTIFY_SECRET")
		supplied := r.Header.Get("X-Notify-Secret")
		detailed := secret != "" && supplied != "" &&
			constantTimeCompare(secret, supplied)

		checks := map[string]any{"ok": true}
		if err := checkDB(r.Context(), p); err != nil {
			checks["db"] = "error"
			checks["ok"] = false
		}
		checks["redis"] = "not_configured"

		status := http.StatusOK
		if !checks["ok"].(bool) {
			status = http.StatusServiceUnavailable
		}
		body := checks
		if !detailed {
			body = map[string]any{"ok": checks["ok"]}
		}
		writeJSON(w, status, body)
	})
}

func checkDB(ctx context.Context, p *store.Pool) error {
	_, err := p.Exec(ctx, "SELECT 1")
	return err
}

func constantTimeCompare(a, b string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := 0; i < len(a); i++ {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	data, err := json.Marshal(v)
	if err != nil {
		http.Error(w, `{"detail":"marshal error"}`, http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	fmt.Fprint(w, string(data))
}
