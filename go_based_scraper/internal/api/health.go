// /health liveness probe.
package api

import (
	"context"
	"net/http"

	"confnotifier/internal/store"
)

// handleHealth reports liveness. Anonymous callers get only {"ok": ...}; the
// per-dependency breakdown is reserved for the internal secret (Docker
// healthcheck and operators), so a probe never leaks which backing service is
// down.
func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	checks := map[string]any{"ok": true}

	if err := checkDB(r.Context(), s.pool); err != nil {
		checks["db"] = "error"
		checks["ok"] = false
	}

	detailed := internalDetailed(r)
	status := http.StatusOK
	if !checks["ok"].(bool) {
		status = http.StatusServiceUnavailable
	}
	body := checks
	if !detailed {
		body = map[string]any{"ok": checks["ok"]}
	}
	writeJSON(w, status, body)
}

// checkDB pings the database through the pool.
func checkDB(ctx context.Context, p *store.Pool) error {
	_, err := p.Query(ctx, "SELECT 1")
	return err
}
