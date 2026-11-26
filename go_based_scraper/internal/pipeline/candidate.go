package pipeline

import (
	"context"
	"log"
	"time"

	"confnotifier/internal/conf"
	"confnotifier/internal/extract"
	"confnotifier/internal/store"
)

// Extractor fetches a URL's text and turns it into a normalised extraction.
// The production implementation uses the browser/fetch tiers + LLM; tests use
// a fake.
type Extractor interface {
	Extract(ctx context.Context, url string) (string, error)
	ExtractConferences(ctx context.Context, pageText, sourceURL string, previousDeadlines map[string]any, now time.Time, client *extract.Client) (extract.ExtractResult, error)
	DailyExhausted() bool
}

// Store is the subset of the data layer the processor depends on. The concrete
// *store.Pool satisfies it; tests supply a fake so the processor can be
// exercised without a database.
type Store interface {
	SaveConference(ctx context.Context, result map[string]any, existingID int) (*store.SaveConferenceResult, error)
	StoredSubmissionDeadlines(ctx context.Context, website string) (map[string]any, error)
	MarkNotified(ctx context.Context, confID int) error
	IncrementRetry(ctx context.Context, url string) error
}

// CandidateProcessor runs one candidate through precheck -> extract ->
// validate -> save -> notify, returning the outcome (scraper/pipeline/runner/
// candidate.py::_process_candidate).
type CandidateProcessor struct {
	store     Store
	index     *store.ConferenceIndex
	terminal  map[string]bool
	retryable map[string]bool
	client    *extract.Client
	extract   Extractor
	nowf      func() time.Time
	stats     *RunStats
	notifier  Notifier
	logger    *log.Logger
	dryRun    bool
}

// SetDryRun toggles dry-run mode. When true, no DB writes (SaveConference,
// MarkNotified, IncrementRetry) and no Telegram notifications happen; the
// processor still runs discovery/extraction/validation and reports what it
// *would* save, so a dry run validates the pipeline without touching prod.
func (cp *CandidateProcessor) SetDryRun(v bool) { cp.dryRun = v }

// Notifier announces a saved conference to the channel.
type Notifier interface {
	Notify(ctx context.Context, conf map[string]any) (bool, error)
}

// NewCandidateProcessor builds a processor. now defaults to time.Now.
func NewCandidateProcessor(st Store, index *store.ConferenceIndex, terminal []string,
	retryable []string, client *extract.Client, ext Extractor, stats *RunStats, nf Notifier, logger *log.Logger) *CandidateProcessor {
	term := make(map[string]bool, len(terminal))
	for _, u := range terminal {
		term[u] = true
	}
	var retry map[string]bool
	if retryable != nil {
		retry = make(map[string]bool, len(retryable))
		for _, u := range retryable {
			retry[u] = true
		}
	}
	if logger == nil {
		logger = log.Default()
	}
	return &CandidateProcessor{
		store: st, index: index, terminal: term, retryable: retry, client: client,
		extract: ext, stats: stats, notifier: nf, logger: logger,
	}
}

func (cp *CandidateProcessor) now() time.Time {
	if cp.nowf != nil {
		return cp.nowf()
	}
	return time.Now().UTC()
}

// Process runs one candidate and returns its outcome.
func (cp *CandidateProcessor) Process(ctx context.Context, url string) (string, Outcome) {
	// Retryable URLs count one more attempt.
	if cp.retryable != nil {
		if _, retrying := cp.retryable[url]; retrying {
			if cp.dryRun {
				cp.stats.Bump("retry")
			} else {
				_ = cp.store.IncrementRetry(ctx, url)
			}
		}
	}
	// Precheck: reject stale/duplicate/terminal before spending an LLM call.
	if cp.terminal[url] {
		cp.logger.Printf("Already decided, skipping: %s", url)
		return url, AlreadyDecided
	}
	if cp.index.FindByUrl(url) != 0 {
		cp.logger.Printf("Duplicate (URL already saved), skipping: %s", url)
		return url, DuplicateURL
	}
	if accepted, reason := conf.ClassifyLink(url, cp.now()); !accepted &&
		(reason == "stale_year" || reason == "stale_wording") {
		cp.logger.Printf("Stale edition (%s), skipping: %s", reason, url)
		return url, StaleURL
	}

	cp.logger.Printf("Extracting data from: %s", url)
	result, err := cp.doExtract(ctx, url)
	if err != nil || result == nil {
		if cp.extract.DailyExhausted() {
			cp.stats.MarkQuotaExhausted()
		}
		cp.logger.Printf("Extraction failed for: %s", url)
		return url, FailedExtraction
	}
	if !result["is_conference"].(bool) {
		cp.logger.Printf("Not a conference: %s", url)
		return url, NotConference
	}
	confidence, _ := result["confidence"].(float64)
	if confidence < minConfidence {
		cp.logger.Printf("Low confidence %.2f for %s", confidence, url)
		return url, LowConfidence
	}
	if conf.IsConferenceInPast(result, cp.now()) {
		cp.logger.Printf("Conference already past: %s", url)
		return url, PastConference
	}
	// Dedup by website / identity.
	reported := asString(result["website"])
	if reported == "" {
		reported = url
	}
	existingID := 0
	if id := cp.index.FindByUrl(reported); id != 0 {
		cp.logger.Printf("Duplicate conference (website already saved): %s", url)
		return url, DuplicateURL
	}
	// Stored deadlines for validation.
	stored := cp.storedDeadlines(ctx, reported)
	verdict := conf.ValidateExtraction(result, stored, cp.now())
	if !verdict.Ok {
		if verdict.Permanent {
			cp.logger.Printf("%s at %s — not retrying", verdict.Reason, url)
			return url, InvalidPermanent
		}
		cp.logger.Printf("%s at %s — retry next run", verdict.Reason, url)
		return url, FailedValidation
	}
	return cp.saveAndNotify(ctx, url, result, existingID)
}

func (cp *CandidateProcessor) doExtract(ctx context.Context, url string) (map[string]any, error) {
	text, err := cp.extract.Extract(ctx, url)
	if err != nil {
		return nil, err
	}
	return cp.extract.ExtractConferences(ctx, text, url, nil, cp.now(), cp.client)
}

func (cp *CandidateProcessor) saveAndNotify(ctx context.Context, url string, result map[string]any, existingID int) (string, Outcome) {
	if cp.dryRun {
		cp.stats.Bump("inserted")
		cp.logger.Printf("DRY-RUN would save conference: %s", asString(result["title"]))
		return url, Saved
	}
	result["raw_source"] = url
	res, err := cp.store.SaveConference(ctx, result, existingID)
	if err != nil || !res.Success {
		cp.logger.Printf("Conference save failed for %s — will retry next run", url)
		return url, FailedSave
	}
	if res.ConfID != 0 {
		cp.index.Add(res.ConfID, asString(result["website"]), asString(result["title"]),
			asString(result["date_start"]), toAnySlice(conf.ExtractedDeadlines(result)))
	}
	if existingID != 0 {
		cp.logger.Printf("Merged duplicate edition into conference %d", existingID)
		cp.stats.Bump("merged")
		return url, DuplicateEdition
	}
	if !res.WasInserted {
		cp.logger.Printf("Conference already in DB (deadlines refreshed): %s", asString(result["title"]))
		cp.stats.Bump("updated")
		return url, Updated
	}
	cp.stats.Bump("inserted")
	cp.logger.Printf("New conference saved: %s", asString(result["title"]))
	if !conf.HasUsableContent(result) {
		cp.stats.Bump("tba")
		cp.logger.Printf("TBA conference (no dates yet): %s", asString(result["title"]))
	}
	if res.ConfID != 0 && hasDeadlineWithinDays(result, notifyWindowDays, cp.now()) {
		if ok, err := cp.notifier.Notify(ctx, result); ok && err == nil {
			_ = cp.store.MarkNotified(ctx, res.ConfID)
			cp.stats.Bump("notifications")
		}
	} else {
		cp.logger.Printf("No deadline within %d days — saved but not announced", notifyWindowDays)
	}
	return url, Saved
}

func (cp *CandidateProcessor) storedDeadlines(ctx context.Context, website string) map[string]any {
	stored, err := cp.store.StoredSubmissionDeadlines(ctx, website)
	if err != nil {
		cp.logger.Printf("stored deadlines error for %s: %v", website, err)
	}
	return stored
}

func asString(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	return ""
}

// toAnySlice converts a []string to []any for the dedup index.
func toAnySlice(in []string) []any {
	out := make([]any, len(in))
	for i, s := range in {
		out[i] = s
	}
	return out
}

// hasDeadlineWithinDays reports whether any deadline falls in [now, now+days].
func hasDeadlineWithinDays(result map[string]any, days int, now time.Time) bool {
	for _, typ := range conf.SubmissionTypes {
		d := conf.CoerceDate(result[typ+"_deadline"])
		if d.IsZero() {
			continue
		}
		ds := d.Sub(now).Hours() / 24
		if ds >= 0 && ds <= float64(days) {
			return true
		}
	}
	return false
}
