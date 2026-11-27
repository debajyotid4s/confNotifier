// HTTP middleware: recovery, logging, gzip, security headers, CORS.
package api

import (
	gz "compress/gzip"
	"log"
	"net/http"
	"strings"
	"time"
)

// securityHeaders applied to every response. The API serves JSON to a native
// client, so it is never treated as a browsable document.
var securityHeaders = map[string]string{
	"X-Content-Type-Options":       "nosniff",
	"X-Frame-Options":              "DENY",
	"Referrer-Policy":              "no-referrer",
	"Cross-Origin-Resource-Policy": "same-site",
	"Content-Security-Policy":      "default-src 'none'; frame-ancestors 'none'",
	"Cache-Control":                "no-store",
}

// corsOrigins returns the allowed browser origins (see main.py _cors_origins).
func corsOrigins() []string {
	raw := getenvDefault("CORS_ORIGINS", "https://confnotifier.onrender.com")
	var out []string
	for _, o := range strings.Split(raw, ",") {
		if o = strings.TrimSpace(o); o != "" {
			out = append(out, o)
		}
	}
	return out
}

// middleware wraps a handler with the shared pipeline.
func middleware(next http.Handler) http.Handler {
	return recovery(cors(sanitizeHeaders(gzip(logRequests(next)))))
}

func logRequests(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		next.ServeHTTP(w, r)
		log.Printf("%s %s %s %s", r.RemoteAddr, r.Method, r.URL.Path, time.Since(start))
	})
}

func recovery(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if rec := recover(); rec != nil {
				log.Printf("panic: %v", rec)
				writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "internal server error"})
			}
		}()
		next.ServeHTTP(w, r)
	})
}

func sanitizeHeaders(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		for k, v := range securityHeaders {
			w.Header().Set(k, v)
		}
		w.Header().Set("Content-Type", "application/json")
		next.ServeHTTP(w, r)
	})
}

func cors(next http.Handler) http.Handler {
	origins := corsOrigins()
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		origin := r.Header.Get("Origin")
		if origin != "" && containsOrigin(origins, origin) {
			w.Header().Set("Access-Control-Allow-Origin", origin)
			w.Header().Set("Vary", "Origin")
			w.Header().Set("Access-Control-Allow-Credentials", "true")
		}
		if r.Method == http.MethodOptions {
			w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS, PATCH")
			w.Header().Set("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Notify-Secret")
			w.WriteHeader(http.StatusNoContent)
			return
		}
		next.ServeHTTP(w, r)
	})
}

// gzip buffers the response and, when the client accepts it and the body is at
// least gzipMinSize, rewrites it through compress/gzip. Small responses and
// bodyless responses (204/304) pass through uncompressed. The whole body is
// buffered so Content-Encoding can be added before the real header is sent, and
// so a handler that panics before writing leaves the response open for the
// recovery middleware to fill in (no double WriteHeader, no empty gzipped body).
func gzip(next http.Handler) http.Handler {
	const gzipMinSize = 512
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !strings.Contains(r.Header.Get("Accept-Encoding"), "gzip") {
			next.ServeHTTP(w, r)
			return
		}
		gw := &gzipResponseWriter{ResponseWriter: w, minSize: gzipMinSize}
		defer gw.flush()
		next.ServeHTTP(gw, r)
	})
}

type gzipResponseWriter struct {
	http.ResponseWriter
	minSize int

	status      int // captured status (0 == unset, defaults to 200)
	wroteHeader bool
	buf         []byte
}

// WriteHeader captures the status without forwarding it: the body is buffered
// so Content-Encoding can be set before the real header is emitted in flush.
func (g *gzipResponseWriter) WriteHeader(code int) {
	if g.wroteHeader {
		return
	}
	g.wroteHeader = true
	g.status = code
}

func (g *gzipResponseWriter) Write(b []byte) (int, error) {
	g.buf = append(g.buf, b...)
	return len(b), nil
}

func (g *gzipResponseWriter) flush() {
	code := g.status
	if code == 0 {
		code = http.StatusOK
	}

	// Bodyless response: forward the captured status (if any) uncompressed and
	// leave the response open if nothing was written, so a recovery writer can
	// still respond.
	if len(g.buf) == 0 {
		if g.wroteHeader {
			g.ResponseWriter.WriteHeader(code)
		}
		return
	}

	// 204/304 must never carry Content-Encoding, and small bodies are not worth
	// compressing.
	if code == http.StatusNoContent || code == http.StatusNotModified || len(g.buf) < g.minSize {
		if g.wroteHeader {
			g.ResponseWriter.WriteHeader(code)
		}
		_, _ = g.ResponseWriter.Write(g.buf)
		return
	}

	g.ResponseWriter.Header().Set("Content-Encoding", "gzip")
	g.ResponseWriter.Header().Del("Content-Length")
	g.ResponseWriter.WriteHeader(code)
	gw := gz.NewWriter(g.ResponseWriter)
	_, _ = gw.Write(g.buf)
	_ = gw.Close()
}

func containsOrigin(origins []string, origin string) bool {
	for _, o := range origins {
		if o == origin {
			return true
		}
	}
	return false
}
