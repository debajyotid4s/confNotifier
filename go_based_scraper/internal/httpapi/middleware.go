// HTTP middleware: recovery, logging, gzip, security headers, CORS.
package httpapi

import (
	"fmt"
	"net/http"
	"strings"
	"time"
)

// securityHeaders applied to every response.
var securityHeaders = map[string]string{
	"X-Content-Type-Options":       "nosniff",
	"X-Frame-Options":              "DENY",
	"Referrer-Policy":              "no-referrer",
	"Cross-Origin-Resource-Policy": "same-site",
	"Content-Security-Policy":      "default-src 'none'; frame-ancestors 'none'",
	"Cache-Control":                "no-store",
}

func middleware(next http.Handler) http.Handler {
	return recovery(sanitizeHeaders(gzip(log(next))))
}

func log(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		next.ServeHTTP(w, r)
		fmt.Printf("%s %s %s %s\n", r.RemoteAddr, r.Method, r.URL.Path, time.Since(start).String())
	})
}

func recovery(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if err := recover(); err != nil {
				fmt.Printf("panic: %v\n", err)
				http.Error(w, `{"detail":"internal server error"}`, http.StatusInternalServerError)
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

func gzip(next http.Handler) http.Handler {
	const gzipMinSize = 512
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		accept := r.Header.Get("Accept-Encoding")
		if !strings.Contains(accept, "gzip") {
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
	buf     []byte
	minSize int
}

func (g *gzipResponseWriter) Write(b []byte) (int, error) {
	g.buf = append(g.buf, b...)
	if len(g.buf) >= g.minSize {
		return g.flushWrite()
	}
	return len(b), nil
}

func (g *gzipResponseWriter) flush() {
	if len(g.buf) > 0 {
		_, _ = g.ResponseWriter.Write(g.buf)
	}
}

func (g *gzipResponseWriter) flushWrite() (int, error) {
	n := len(g.buf)
	g.buf = nil
	g.ResponseWriter.Header().Set("Content-Encoding", "gzip")
	return g.ResponseWriter.Write(g.buf[:0:n])
}
