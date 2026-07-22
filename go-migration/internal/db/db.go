package db

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/anomalyco/bd-conf-bot/internal/models"
)

type Pool struct {
	*pgxpool.Pool
}

func Connect(ctx context.Context, databaseURL string) (*Pool, error) {
	cfg, err := pgxpool.ParseConfig(databaseURL)
	if err != nil {
		return nil, fmt.Errorf("parse config: %w", err)
	}
	cfg.MaxConns = 5
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, fmt.Errorf("connect: %w", err)
	}
	if err := pool.Ping(ctx); err != nil {
		return nil, fmt.Errorf("ping: %w", err)
	}
	return &Pool{pool}, nil
}

func (p *Pool) IsLinkSeen(ctx context.Context, url string) (bool, error) {
	var exists bool
	err := p.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM seen_links WHERE url = $1)", url).Scan(&exists)
	return exists, err
}

func (p *Pool) SaveSeenLink(ctx context.Context, url, source string) error {
	_, err := p.Exec(ctx,
		`INSERT INTO seen_links (url, source) VALUES ($1, $2)
		 ON CONFLICT (url) DO UPDATE SET last_seen = NOW(), status = 'pending'`,
		url, source)
	return err
}

func (p *Pool) LoadDomainStrategies(ctx context.Context) (map[string]models.DomainStrategy, error) {
	rows, err := p.Query(ctx, "SELECT domain, strategy, loaded_url FROM domain_strategies")
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	strategies := make(map[string]models.DomainStrategy)
	for rows.Next() {
		var ds models.DomainStrategy
		if err := rows.Scan(&ds.Domain, &ds.Strategy, &ds.LoadedURL); err != nil {
			return nil, err
		}
		strategies[ds.Domain] = ds
	}
	return strategies, rows.Err()
}

func (p *Pool) SaveDomainStrategy(ctx context.Context, domain, strategy, loadedURL string) error {
	_, err := p.Exec(ctx,
		`INSERT INTO domain_strategies (domain, strategy, loaded_url, updated_at)
		 VALUES ($1, $2, $3, NOW())
		 ON CONFLICT (domain) DO UPDATE SET strategy = $2, loaded_url = $3, updated_at = NOW()`,
		domain, strategy, loadedURL)
	return err
}

func (p *Pool) SaveConference(ctx context.Context, conf *models.Conference) (int, bool, error) {
	var id int
	var inserted bool
	err := p.QueryRow(ctx,
		`INSERT INTO conferences (title, date_start, date_end, city, country, website, organizer, category, confidence)
		 VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
		 ON CONFLICT (website, COALESCE(date_start, '1970-01-01')) DO UPDATE
		   SET updated_at = NOW()
		 RETURNING id, created_at = updated_at AS inserted`,
		conf.Title, conf.DateStart, conf.DateEnd, conf.City, conf.Country,
		conf.Website, conf.Organizer, conf.Category, conf.Confidence,
	).Scan(&id, &inserted)
	if err != nil {
		return 0, false, fmt.Errorf("save conference: %w", err)
	}
	return id, inserted, nil
}

func (p *Pool) MarkNotified(ctx context.Context, confID int) error {
	_, err := p.Exec(ctx,
		`UPDATE conferences SET is_notified = TRUE, notified_at = NOW() WHERE id = $1`,
		confID)
	return err
}

func (p *Pool) IsEditionInDB(ctx context.Context, website string, year int) (bool, error) {
	var exists bool
	err := p.QueryRow(ctx,
		`SELECT EXISTS(
			SELECT 1 FROM conferences
			WHERE website = $1
			  AND date_start >= $2::date
			  AND date_start < ($2 + 1)::date
		)`,
		website, fmt.Sprintf("%d-01-01", year),
	).Scan(&exists)
	return exists, err
}

func (p *Pool) GetPendingConferencesForNotification(ctx context.Context) ([]models.Conference, error) {
	rows, err := p.Query(ctx,
		`SELECT id, title, date_start, date_end, city, country, website, organizer, category,
		        confidence, is_notified, created_at, updated_at
		 FROM conferences
		 WHERE is_notified = FALSE AND confidence >= 0.75
		 ORDER BY created_at DESC`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var confs []models.Conference
	for rows.Next() {
		var c models.Conference
		if err := rows.Scan(
			&c.ID, &c.Title, &c.DateStart, &c.DateEnd,
			&c.City, &c.Country, &c.Website, &c.Organizer,
			&c.Category, &c.Confidence, &c.IsNotified,
			&c.CreatedAt, &c.UpdatedAt,
		); err != nil {
			return nil, err
		}
		confs = append(confs, c)
	}
	return confs, rows.Err()
}

func (p *Pool) GetDeadlinesDue(ctx context.Context, beforeDays int) ([]models.Conference, error) {
	rows, err := p.Query(ctx,
		`SELECT id, title, date_start, date_end, city, country, website, organizer, category,
		        confidence, submission_deadline, submission_deadline_label, is_notified, created_at, updated_at
		 FROM conferences
		 WHERE submission_deadline IS NOT NULL
		   AND submission_deadline <= CURRENT_DATE + $1
		   AND submission_deadline >= CURRENT_DATE
		   AND (deadline_last_verified IS NULL OR deadline_last_verified < CURRENT_DATE - 1)
		 ORDER BY submission_deadline`,
		beforeDays,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var confs []models.Conference
	for rows.Next() {
		var c models.Conference
		if err := rows.Scan(
			&c.ID, &c.Title, &c.DateStart, &c.DateEnd,
			&c.City, &c.Country, &c.Website, &c.Organizer, &c.Category,
			&c.Confidence, &c.SubmissionDeadline, &c.SubmissionDeadlineLabel,
			&c.IsNotified, &c.CreatedAt, &c.UpdatedAt,
		); err != nil {
			return nil, err
		}
		confs = append(confs, c)
	}
	return confs, rows.Err()
}

func (p *Pool) TaskLastRun(ctx context.Context, taskName string) (*time.Time, error) {
	var lastRun time.Time
	err := p.QueryRow(ctx,
		`SELECT last_run_date FROM daily_tasks WHERE task_name = $1`, taskName,
	).Scan(&lastRun)
	if err != nil {
		return nil, nil // not found
	}
	return &lastRun, nil
}

func (p *Pool) SetTaskRun(ctx context.Context, taskName string) error {
	_, err := p.Exec(ctx,
		`INSERT INTO daily_tasks (task_name, last_run_date)
		 VALUES ($1, CURRENT_DATE)
		 ON CONFLICT (task_name) DO UPDATE SET last_run_date = CURRENT_DATE`,
		taskName)
	return err
}

func (p *Pool) LoadKnownWebsites(ctx context.Context) ([]string, error) {
	rows, err := p.Query(ctx, "SELECT DISTINCT website FROM conferences WHERE website IS NOT NULL")
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var websites []string
	for rows.Next() {
		var w string
		if err := rows.Scan(&w); err != nil {
			return nil, err
		}
		websites = append(websites, w)
	}
	return websites, rows.Err()
}
