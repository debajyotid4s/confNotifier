// REST API server: wiring, route registration, graceful shutdown.
package api

import (
	"context"
	"fmt"
	"net/http"
	"strings"
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

// Register wires every route onto the mux. Every public read is served at both
// its unversioned path (the existing Android contract) and under /api/v1 (the
// versioned public API); the three conference reads are rate-limited per client
// IP. /health is operational, not a read, so it is left un-limited.
func (s *Server) Register(mux *http.ServeMux) {
	mux.HandleFunc("GET /health", s.handleHealth)
	mux.HandleFunc("GET /api/v1/health", s.handleHealth)

	mux.HandleFunc("POST /auth/login", s.handleLogin)
	mux.HandleFunc("POST /auth/logout", s.authMiddleware(s.handleLogout))

	mux.HandleFunc("GET /me", s.authMiddleware(s.handleMe))
	mux.HandleFunc("DELETE /me", s.authMiddleware(s.handleDeleteMe))

	registerRead(mux, "GET /conferences/calendar", s.limitedRead(s.handleCalendar))
	registerRead(mux, "GET /conferences/upcoming", s.limitedRead(s.handleUpcoming))
	registerRead(mux, "GET /conferences/{conf_id}", s.limitedRead(s.handleConference))

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

// registerRead wires a read handler at both the unversioned path and its
// /api/v1 counterpart, so the existing Android endpoints keep working while the
// versioned public API is available. The same (already rate-limited) handler
// serves both, so an IP is bounded across the two prefixes. The ServeMux pattern
// is "METHOD /path"; the /api/v1 prefix is inserted on the path only, keeping
// the method first.
func registerRead(mux *http.ServeMux, pattern string, h http.HandlerFunc) {
	mux.HandleFunc(pattern, h)
	if sp := strings.IndexByte(pattern, ' '); sp >= 0 {
		mux.HandleFunc(pattern[:sp]+" /api/v1"+pattern[sp+1:], h)
	}
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
