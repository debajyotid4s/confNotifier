// HTTP server with timeouts and graceful shutdown.
package httpapi

import (
	"context"
	"fmt"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"
)

const (
	readHeaderTimeout = 5 * time.Second
	readTimeout       = 10 * time.Second
	writeTimeout      = 10 * time.Second
	idleTimeout       = 30 * time.Second
	maxBodyBytes      = 1 << 20
)

// Mux wraps http.ServeMux for route registration.
type Mux struct {
	*http.ServeMux
}

// NewMux creates a new Mux.
func NewMux() *Mux {
	return &Mux{http.NewServeMux()}
}

// DefaultMux returns a new default Mux.
func DefaultMux() *Mux {
	return NewMux()
}

// NewServer creates the HTTP server with all routes.
func NewServer() *http.Server {
	mux := http.NewServeMux()
	handler := middleware(mux)
	return &http.Server{
		Addr:              fmt.Sprintf(":%s", port()),
		Handler:           handler,
		ReadHeaderTimeout: readHeaderTimeout,
		ReadTimeout:       readTimeout,
		WriteTimeout:      writeTimeout,
		IdleTimeout:       idleTimeout,
		MaxHeaderBytes:    1 << 20,
	}
}

// Start runs the server and blocks until a signal arrives.
func Start() error {
	srv := NewServer()
	go func() {
		fmt.Printf("api: listening on %s\n", srv.Addr)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			fmt.Printf("api: serve error: %v\n", err)
		}
	}()
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	return srv.Shutdown(ctx)
}

func port() string {
	p := os.Getenv("PORT")
	if p == "" {
		return "8080"
	}
	return p
}
