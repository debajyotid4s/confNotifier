// JSON request/response helpers.
package api

import (
	"encoding/json"
	"io"
	"net/http"
)

// maxBodyBytes caps request bodies. A login token or FCM token is small; anything
// larger is almost certainly a mistake or an abuse vector.
const maxBodyBytes = 1 << 20 // 1 MiB

// writeJSON serialises v and writes it with the given status code.
func writeJSON(w http.ResponseWriter, status int, v any) {
	data, err := json.Marshal(v)
	if err != nil {
		http.Error(w, `{"detail":"marshal error"}`, http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_, _ = w.Write(data)
}

// readJSON reads and parses a JSON object body into v. It rejects empty bodies
// and non-object payloads, returning (false, nil) when nothing should be read.
func readJSON(r *http.Request, v any) (bool, error) {
	body, err := io.ReadAll(io.LimitReader(r.Body, maxBodyBytes))
	if err != nil {
		return false, err
	}
	s := string(body)
	if s == "" {
		return false, nil
	}
	if err := json.Unmarshal([]byte(s), v); err != nil {
		return false, err
	}
	return true, nil
}

// jsonBody is readJSON that returns a 400 on failure (the common call site).
func jsonBody(r *http.Request, v any) error {
	if _, err := readJSON(r, v); err != nil {
		return err
	}
	return nil
}
