// Typed API errors for concise handler error responses.
package api

import (
	"errors"
	"net/http"
)

// apiError is an error with an HTTP status and detail message.
type apiError struct {
	status int
	detail string
}

func (e *apiError) Error() string { return e.detail }

func (e *apiError) Status() int { return e.status }

// Common errors.
var (
	errInvalid     = &apiError{http.StatusUnauthorized, "Invalid token"}
	errNotFound    = &apiError{http.StatusNotFound, "Not found"}
	errConflict    = &apiError{http.StatusConflict, "Conflict"}
	errBadRequest  = &apiError{http.StatusBadRequest, "Bad request"}
	errRateLimited = &apiError{http.StatusTooManyRequests, "Too many requests — try again later"}
	errInternal    = &apiError{http.StatusInternalServerError, "Internal server error"}
)

// fail writes an apiError as a JSON response. Non-apiError values become 500.
func fail(w http.ResponseWriter, err error) {
	var ae *apiError
	if errors.As(err, &ae) {
		writeJSON(w, ae.status, map[string]any{"detail": ae.detail})
		return
	}
	writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "internal server error"})
}
