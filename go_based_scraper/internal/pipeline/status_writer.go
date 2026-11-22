package pipeline

import "sync"

// StatusWriter buffers seen_links status writes and flushes them in batches
// (scraper/pipeline/status_writer.py).
type StatusWriter struct {
	mu         sync.Mutex
	pending    [][2]string // (url, status)
	flushEvery int
	onFlush    func(rows [][2]string)
}

// NewStatusWriter builds a writer that flushes via onFlush every flushEvery.
func NewStatusWriter(flushEvery int, onFlush func(rows [][2]string)) *StatusWriter {
	if flushEvery <= 0 {
		flushEvery = statusFlushEvery
	}
	return &StatusWriter{flushEvery: flushEvery, onFlush: onFlush}
}

// Set buffers a status for a URL. Empty status is ignored.
func (w *StatusWriter) Set(url, status string) {
	if status == "" {
		return
	}
	w.mu.Lock()
	w.pending = append(w.pending, [2]string{url, status})
	n := len(w.pending)
	w.mu.Unlock()
	if n >= w.flushEvery && w.onFlush != nil {
		w.flush()
	}
}

// Flush writes any buffered statuses.
func (w *StatusWriter) Flush() {
	w.mu.Lock()
	defer w.mu.Unlock()
	w.flush()
}

func (w *StatusWriter) flush() {
	if len(w.pending) == 0 || w.onFlush == nil {
		return
	}
	rows := w.pending
	w.pending = nil
	w.onFlush(rows)
}
