// REST API server: wiring, route registration, graceful shutdown.
package api

import (
	"context"
	"fmt"
	"net/http"
	"time"

	"confnotifier/internal/store"
)

const (
	readHeaderTimeout = 5 * time.Second
	readTimeout       = 10 * time.Second
	writeTimeout      = 10 * time.Second
	idleTimeout       = 30 * time.Second
)

// Server holds the shared dependencies for all handlers.
type Server struct {
	pool      *store.Pool
	jwt       *jwtManager
	limiter   *RateLimiter
	fcm       *FCMClient
	notifyCfg notifyConfig
}

// notifyConfig holds the internal-notification settings.
type notifyConfig struct {
	broadcastTopic string
	fcmBatch       int
}

// NewServer builds a server over an existing DB pool.
func NewServer(p *store.Pool) *Server {
	return &Server{
		pool: p,
		jwt:  newJWTManager(),
		limiter: NewRateLimiter(
			envInt("PUBLIC_RATE_LIMIT", 60),
			time.Duration(envInt("PUBLIC_RATE_WINDOW", 60))*time.Second,
		),
		fcm:       newFCMClient(),
		notifyCfg: notifyConfig{broadcastTopic: "all_users", fcmBatch: 500},
	}
}

// Handler returns the fully-wired HTTP handler (middleware + routes).
func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	s.Register(mux)
	return middleware(mux)
}

// Register wires every route onto the mux.
func (s *Server) Register(mux *http.ServeMux) {
	mux.HandleFunc("GET /health", s.handleHealth)

	mux.HandleFunc("POST /auth/login", s.handleLogin)
	mux.HandleFunc("POST /auth/logout", s.authMiddleware(s.handleLogout))

	mux.HandleFunc("GET /me", s.authMiddleware(s.handleMe))
	mux.HandleFunc("DELETE /me", s.authMiddleware(s.handleDeleteMe))

	mux.HandleFunc("GET /conferences/calendar", s.handleCalendar)
	mux.HandleFunc("GET /conferences/upcoming", s.handleUpcoming)
	mux.HandleFunc("GET /conferences/{conf_id}", s.handleConference)

	mux.HandleFunc("GET /me/bookmarks", s.authMiddleware(s.handleListBookmarks))
	mux.HandleFunc("POST /me/bookmarks/{conference_id}", s.authMiddleware(s.handleAddBookmark))
	mux.HandleFunc("DELETE /me/bookmarks/{conference_id}", s.authMiddleware(s.handleRemoveBookmark))

	mux.HandleFunc("POST /me/devices", s.authMiddleware(s.handleUpsertDevice))
	mux.HandleFunc("DELETE /me/devices/{token}", s.authMiddleware(s.handleDeleteDevice))

	mux.HandleFunc("POST /internal/notify-scraper-run", s.internalMiddleware(s.handleScraperRun))
	mux.HandleFunc("POST /internal/notify-bookmarks", s.internalMiddleware(s.handleNotifyBookmarks))
	mux.HandleFunc("POST /internal/notify-digest", s.internalMiddleware(s.handleNotifyDigest))
	mux.HandleFunc("POST /internal/notify-daily", s.internalMiddleware(s.handleNotifyDaily))
}

// Start runs the server and blocks until SIGINT/SIGTERM, then shuts down.
func (s *Server) Start() error {
	srv := &http.Server{
		Addr:              fmt.Sprintf(":%s", port()),
		Handler:           s.Handler(),
		ReadHeaderTimeout: readHeaderTimeout,
		ReadTimeout:       readTimeout,
		WriteTimeout:      writeTimeout,
		IdleTimeout:       idleTimeout,
		MaxHeaderBytes:    1 << 20,
	}
	errc := make(chan error, 1)
	go func() {
		fmt.Printf("api: listening on %s\n", srv.Addr)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			errc <- err
		}
	}()
	select {
	case err := <-errc:
		return err
	case sig := <-chanSignal():
		fmt.Printf("api: received %v, shutting down\n", sig)
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		return srv.Shutdown(ctx)
	}
}
