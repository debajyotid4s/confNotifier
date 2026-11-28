// Database pool configuration for Neon/PgBouncer.
package store

import (
	"context"
	"fmt"
	"log"
	"os"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

const (
	poolMinConns    = 1
	poolMaxConns    = 10
	healthCheckFreq = 30 * time.Second
	maxConnIdle     = 30 * time.Second
	maxConnLife     = 5 * time.Minute
	stmtTimeoutMs   = 8000
)

// Pool wraps a pgxpool.Pool with health-check and retry logic.
type Pool struct {
	*pgxpool.Pool
}

// NewPool opens a connection pool. It retries up to 3 times.
func NewPool(ctx context.Context) (*Pool, error) {
	dsn := os.Getenv("DATABASE_URL")
	if dsn == "" {
		return nil, fmt.Errorf("DATABASE_URL not set")
	}
	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		return nil, fmt.Errorf("parse db url: %w", err)
	}
	cfg.MaxConns = poolMaxConns
	cfg.MinConns = poolMinConns
	cfg.MaxConnIdleTime = maxConnIdle
	cfg.MaxConnLifetime = maxConnLife
	cfg.HealthCheckPeriod = healthCheckFreq
	cfg.ConnConfig.RuntimeParams["statement_timeout"] = fmt.Sprintf("%d", stmtTimeoutMs)
	cfg.ConnConfig.RuntimeParams["default_text_search_config"] = "pg_catalog.english"
	for i := 0; i < 3; i++ {
		pool, err := pgxpool.NewWithConfig(ctx, cfg)
		if err != nil {
			log.Printf("DB pool create attempt %d/3 failed: %v", i+1, err)
			continue
		}
		if err := pool.Ping(ctx); err == nil {
			log.Printf("DB pool inited (%d-%d conns)", poolMinConns, poolMaxConns)
			return &Pool{pool}, nil
		}
		log.Printf("DB connect attempt %d/3 failed: %v", i+1, err)
		time.Sleep(2 * time.Second)
	}
	return nil, fmt.Errorf("db unavailable after 3 attempts")
}

// StatementTimeout returns the per-request statement timeout in milliseconds.
func StatementTimeout() string {
	v := os.Getenv("DB_STATEMENT_TIMEOUT_MS")
	if v == "" {
		return fmt.Sprintf("%d", stmtTimeoutMs)
	}
	return v
}
