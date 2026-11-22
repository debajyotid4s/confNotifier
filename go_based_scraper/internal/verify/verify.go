// Package verify re-extracts submission deadlines for upcoming conferences and
// applies any validated change, announcing real moves to the Telegram channel.
// It mirrors scraper/verifier (process + diff + persist).
package verify

import (
	"context"
	"fmt"
	"strings"
	"time"

	"confnotifier/internal/conf"
	"confnotifier/internal/extract"
	"confnotifier/internal/store"
)

// VerifyWindowDays is how far ahead a conference is re-verified.
const VerifyWindowDays = 30

// Extractor re-extracts a conference page into a structured result.
type Extractor interface {
	Extract(ctx context.Context, url string) (string, error)
	ExtractConferences(ctx context.Context, pageText, sourceURL string, previous map[string]any, now time.Time, client *extract.Client) (extract.ExtractResult, error)
}

// Notifier posts a deadline-change message.
type Notifier interface {
	SendPlain(ctx context.Context, text string) (int, error)
}

// Verifier re-checks upcoming conferences.
type Verifier struct {
	pool     *store.Pool
	extract  Extractor
	notifier Notifier
	client   *extract.Client
	nowf     func() time.Time
}

// New builds a Verifier.
func New(p *store.Pool, ext Extractor, nf Notifier, client *extract.Client) *Verifier {
	return &Verifier{pool: p, extract: ext, notifier: nf, client: client, nowf: time.Now}
}

// Run re-extracts deadlines for upcoming conferences and applies validated
// changes. Returns the number of deadline-change notifications sent.
func (v *Verifier) Run(ctx context.Context) (int, error) {
	rows, err := store.LoadVerificationRows(ctx, v.pool, VerifyWindowDays)
	if err != nil {
		return 0, err
	}
	if len(rows) == 0 {
		_ = store.MarkVerificationDone(ctx, v.pool)
		return 0, nil
	}
	sent := 0
	for i := range rows {
		n, err := v.processRow(ctx, rows[i])
		sent += n
		if err != nil {
			fmt.Printf("deadline_verification: error processing %s: %v\n", rows[i].Website, err)
		}
	}
	_ = store.MarkVerificationDone(ctx, v.pool)
	return sent, nil
}

func (v *Verifier) now() time.Time { return v.nowf() }

func (v *Verifier) processRow(ctx context.Context, row store.VerificationRow) (int, error) {
	stored := storedMap(row)
	result, usedURL, err := v.reExtract(ctx, row, stored)
	if err != nil || result == nil {
		return 0, nil
	}
	if usedURL != row.Website {
		fmt.Printf("deadline_verification: re-extracted %s via %s\n", row.Title, usedURL)
	}
	updates, changes := diffDeadlines(result, stored, usedURL)
	if len(updates) == 0 {
		fmt.Printf("deadline_verification: %s — no change\n", row.Website)
		return 0, nil
	}
	sent := 0
	for _, u := range updates {
		if err := store.ApplyDeadlineUpdate(ctx, v.pool, row.ID, u.typ, u.date, u.label); err != nil {
			return sent, err
		}
	}
	if len(changes) > 0 && v.notifier != nil {
		msg := buildChangeMessage(row.Title, usedURL, changes)
		if _, err := v.notifier.SendPlain(ctx, msg); err == nil {
			sent++
		}
	}
	return sent, nil
}

// buildChangeMessage composes the "deadline updated" channel post, rendering
// each move as "<s>old</s> → <b>new</b> 📝 <i>Updated</i>". Mirrors the
// Telegram strikethrough change alert.
func buildChangeMessage(title, website string, changes []deadlineChange) string {
	lines := make([]string, 0, len(changes))
	for _, c := range changes {
		lines = append(lines, fmt.Sprintf("<s>%s</s> → <b>%s</b> 📝 <i>Updated</i>", shortDate(c.old), shortDate(c.new)))
	}
	return fmt.Sprintf("📢 <b>Deadline Updated</b>\n\n<b>%s</b>\n\n%s\n\n🔗 <a href=\"%s\">%s</a>",
		title, strings.Join(lines, "\n"), website, website)
}

// shortDate renders a YYYY-MM-DD date as "Jan 02" for the channel post.
func shortDate(iso string) string {
	if t, err := time.Parse("2006-01-02", iso); err == nil {
		return t.Format("Jan 02")
	}
	return iso
}

func (v *Verifier) reExtract(ctx context.Context, row store.VerificationRow, stored map[string]any) (extract.ExtractResult, string, error) {
	url := row.RawSource
	if url == "" {
		url = row.Website
	}
	text, err := v.extract.Extract(ctx, url)
	if err != nil {
		return nil, url, err
	}
	result, err := v.extract.ExtractConferences(ctx, text, url, stored, v.now(), v.client)
	if err != nil {
		return nil, url, err
	}
	return result, url, nil
}

// storedMap renders a verification row's deadlines as {type: date-string}.
func storedMap(row store.VerificationRow) map[string]any {
	out := map[string]any{}
	if row.AbstractDL != nil {
		out["abstract"] = *row.AbstractDL
	}
	if row.FullPAPERDL != nil {
		out["full_paper"] = *row.FullPAPERDL
	}
	return out
}

// deadlineUpdate is one validated field change.
type deadlineUpdate struct {
	typ   string
	date  string
	label string
}

// deadlineChange is a {old, new, label} move worth announcing.
type deadlineChange struct {
	old   string
	new   string
	label string
}

// diffDeadlines compares a fresh extraction with stored values and returns the
// field updates to apply and the moves to announce. Mirrors
// scraper/verifier/diff._diff_deadlines.
func diffDeadlines(result extract.ExtractResult, stored map[string]any, website string) ([]deadlineUpdate, []deadlineChange) {
	var updates []deadlineUpdate
	var changes []deadlineChange
	for _, typ := range conf.SubmissionTypes {
		newDate := conf.CoerceDate(result[typ+"_deadline"])
		if newDate.IsZero() {
			continue
		}
		oldStr := stored[typ]
		var oldDate time.Time
		if s, ok := oldStr.(string); ok && s != "" {
			if t, err := time.Parse("2006-01-02", s); err == nil {
				oldDate = t
			}
		}
		newISO := newDate.Format("2006-01-02")
		if oldDate.Format("2006-01-02") == newISO {
			continue
		}
		// Reject backward moves unless the stored value matches the other
		// field's freshly extracted date (a previously misplaced value).
		if !oldDate.IsZero() && newDate.Before(oldDate) && !acceptForwardSwap(result, typ, oldDate) {
			fmt.Printf("deadline_verification: %s — %s moved backward %s → %s, skipping\n",
				website, typ, oldDate.Format("2006-01-02"), newISO)
			continue
		}
		label, _ := result[typ+"_deadline_label"].(string)
		if label == "" {
			label = typ
		}
		updates = append(updates, deadlineUpdate{typ: typ, date: newISO, label: label})
		if !oldDate.IsZero() {
			changes = append(changes, deadlineChange{old: oldDate.Format("2006-01-02"), new: newISO, label: label})
		}
	}
	return updates, changes
}

// acceptForwardSwap reports whether a backward move corrects a misplaced value
// (the stored old date now matches the other field's extracted date).
func acceptForwardSwap(result extract.ExtractResult, typ string, oldDate time.Time) bool {
	for _, other := range conf.SubmissionTypes {
		if other == typ {
			continue
		}
		if conf.CoerceDate(result[other+"_deadline"]).Equal(oldDate) {
			return true
		}
	}
	return false
}
