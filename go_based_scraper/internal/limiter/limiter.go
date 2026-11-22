// Package limiter provides a sliding-window rate limiter with a daily cap.
//
// It mirrors the Python GoogleRateLimiter algorithm (a mutex-guarded deque of
// request timestamps plus a daily counter) but is parameterised so it can serve
// any quota: 30 RPM / 1000 RPD for the extraction model, or any other pair.
package limiter

import (
	"sync"
	"time"
)

// Limiter reserves request slots under an RPM limit and a RPD (daily) cap.
//
// Zero values are unusable; construct with New. It is safe for concurrent use.
type Limiter struct {
	mu       sync.Mutex
	window   time.Duration // RPM lookback window
	rpm      int           // max requests per window
	rpd      int           // max requests per day
	now      func() time.Time
	dayStart time.Time
	hits     []time.Time // timestamps inside the current window
	daily    int
}

// Option configures a Limiter.
type Option func(*Limiter)

// WithClock injects a time source (tests). Default is time.Now.
func WithClock(now func() time.Time) Option {
	return func(l *Limiter) { l.now = now }
}

// New creates a limiter allowing rpm requests per window and rpd per day.
// A window of zero means "no RPM enforcement" (daily cap only).
func New(rpm, rpd int, window time.Duration, opts ...Option) *Limiter {
	l := &Limiter{
		window:   window,
		rpm:      rpm,
		rpd:      rpd,
		dayStart: time.Now().Truncate(24 * time.Hour),
	}
	for _, o := range opts {
		o(l)
	}
	if l.now == nil {
		l.now = time.Now
	}
	return l
}

// resetDay rolls the daily counters over if the day has changed.
func (l *Limiter) resetDay() {
	day := l.now().Truncate(24 * time.Hour)
	if !day.Equal(l.dayStart) {
		l.dayStart = day
		l.hits = l.hits[:0]
		l.daily = 0
	}
}

// DailyCount returns how many requests have been taken today.
func (l *Limiter) DailyCount() int {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.resetDay()
	return l.daily
}

// DailyExhausted reports whether the daily cap is spent.
func (l *Limiter) DailyExhausted() bool {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.resetDay()
	return l.daily >= l.rpd
}

// Acquire blocks until a slot is available, then reserves it.
//
// It returns an error immediately if the daily cap is already spent. When the
// RPM limit is hit it waits for the oldest in-window request to expire, exactly
// as the Python limiter sleeps for the remaining window.
func (l *Limiter) Acquire() error {
	l.mu.Lock()
	l.resetDay()
	if l.daily >= l.rpd {
		l.mu.Unlock()
		return ErrDailyExhausted
	}
	for {
		// Evict hits that have fallen out of the window (at or before cutoff).
		if l.window > 0 {
			cutoff := l.now().Add(-l.window)
			for len(l.hits) > 0 && !l.hits[0].After(cutoff) {
				l.hits = l.hits[1:]
			}
		}
		if l.rpm == 0 || len(l.hits) < l.rpm {
			l.hits = append(l.hits, l.now())
			l.daily++
			l.mu.Unlock()
			return nil
		}
		// Window is full: wait until the oldest hit falls out.
		oldest := l.hits[0]
		freeAt := oldest.Add(l.window)
		l.mu.Unlock()

		for {
			l.mu.Lock()
			l.resetDay()
			if l.daily >= l.rpd {
				l.mu.Unlock()
				return ErrDailyExhausted
			}
			if l.window > 0 {
				cutoff := l.now().Add(-l.window)
				for len(l.hits) > 0 && !l.hits[0].After(cutoff) {
					l.hits = l.hits[1:]
				}
			}
			if l.rpm == 0 || len(l.hits) < l.rpm {
				l.hits = append(l.hits, l.now())
				l.daily++
				l.mu.Unlock()
				return nil
			}
			l.mu.Unlock()
			for {
				l.mu.Lock()
				now := l.now()
				l.mu.Unlock()
				if !now.Before(freeAt) {
					break
				}
				time.Sleep(time.Millisecond)
			}
		}
	}
}

// Release returns one RPM slot and one daily count, for a request that failed
// before consuming quota (e.g. a malformed payload). Best-effort.
func (l *Limiter) Release() {
	l.mu.Lock()
	defer l.mu.Unlock()
	if len(l.hits) > 0 {
		l.hits = l.hits[:len(l.hits)-1]
	}
	if l.daily > 0 {
		l.daily--
	}
}

// ErrDailyExhausted is returned by Acquire when the daily cap is spent.
var ErrDailyExhausted = &LimitError{"daily quota exhausted"}

// LimitError describes a rate-limit failure.
type LimitError struct{ msg string }

func (e *LimitError) Error() string { return e.msg }
