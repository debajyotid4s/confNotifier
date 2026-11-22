// Package health provides an HTTP server that serves a /health endpoint.
package health

import (
	"context"
	"fmt"
	"net"
	"net/http"
	"time"
)

// Server runs an HTTP server that serves a GET /health route.
type Server struct {
	addr string
	l    net.Listener
	srv  *http.Server
}

// New creates a health server listening on the given address.
func New(addr string) *Server {
	mux := http.NewServeMux()
	l, err := net.Listen("tcp", addr)
	if err != nil {
		panic(fmt.Sprintf("health: listen %s: %v", addr, err))
	}
	s := &http.Server{
		Handler:           mux,
		ReadHeaderTimeout: 3 * time.Second,
		ReadTimeout:       5 * time.Second,
		WriteTimeout:      5 * time.Second,
		IdleTimeout:       30 * time.Second,
	}
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprintf(w, `{"ok":true}`)
	})
	return &Server{
		addr: l.Addr().String(),
		l:    l,
		srv:  s,
	}
}

// Addr returns the address the server is listening on.
func (s *Server) Addr() string {
	return s.addr
}

// Start begins serving. Blocks until Serve returns.
func (s *Server) Start() error {
	return s.srv.Serve(s.l)
}

// Shutdown gracefully shuts down the server with a 5-second deadline.
func (s *Server) Shutdown() error {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	return s.srv.Shutdown(ctx)
}
