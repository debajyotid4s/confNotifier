package notify

import (
	"context"
	"time"
)

// NotifyWindowDays is how far ahead a saved conference is announced.
const NotifyWindowDays = 30

// Notifier marks a conference as announced. Defined as an interface so the
// sweep can be tested against a fake; production uses the store.
type Notifier interface {
	MarkNotified(ctx context.Context, confID int) error
}

// PendingRow is a conference still awaiting its first announcement.
type PendingRow struct {
	ID          int
	Title       string
	DateStart   string
	DateEnd     *string
	City        string
	Website     string
	Organizer   string
	Category    string
	Description string
	Deadlines   []DeadlinePair
}

// DeadlinePair is a {type, date, label} deadline on a pending row.
type DeadlinePair struct {
	Type  string
	Date  string
	Label string
}

// PendingSource fetches conferences awaiting notification. Implemented by the
// store; fakes supply rows directly in tests.
type PendingSource interface {
	LoadPending(ctx context.Context) ([]PendingRow, error)
}

// PendingSweep announces every conference still flagged unannounced, marking
// each notified only after its Telegram post is accepted. It returns the number
// of notifications actually delivered.
//
// notifyFn posts a message and returns the message id (0 on failure).
// betweenMessage bounds the pause between posts so a long queue cannot race
// ahead of Telegram's ~1 msg/sec channel politeness.
func PendingSweep(ctx context.Context, pending PendingSource, notifier Notifier,
	notifyFn func(ctx context.Context, conf map[string]any) (int, error),
	betweenMessage time.Duration,
) int {
	var rows []PendingRow
	var err error
	if pending != nil {
		rows, err = pending.LoadPending(ctx)
		if err != nil {
			return 0
		}
	}
	if len(rows) == 0 {
		return 0
	}
	sent := 0
	for _, row := range rows {
		conf := pendingConf(row)
		id, perr := notifyFn(ctx, conf)
		if perr != nil || id == 0 {
			continue
		}
		if merr := notifier.MarkNotified(ctx, row.ID); merr != nil {
			continue
		}
		sent++
		if betweenMessage > 0 {
			select {
			case <-ctx.Done():
				return sent
			case <-time.After(betweenMessage):
			}
		}
	}
	return sent
}

func pendingConf(row PendingRow) map[string]any {
	conf := map[string]any{
		"title":       row.Title,
		"date_start":  row.DateStart,
		"city":        row.City,
		"website":     row.Website,
		"organizer":   row.Organizer,
		"category":    row.Category,
		"description": row.Description,
	}
	if row.DateEnd != nil {
		conf["date_end"] = *row.DateEnd
	}
	for _, d := range row.Deadlines {
		conf[d.Type+"_deadline"] = d.Date
	}
	return conf
}
