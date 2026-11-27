// In-memory fixed-window rate limiter.
//
// The Python API rate limits through Redis and fails open when Redis is
// unavailable. This is a single-process limiter that needs no external store:
// it is defence in depth, not the only protection, so failing open is correct.
package api

import (
	"sync"
	"time"
)

// window is a single client's counter for one rate-limit key.
type window struct {
	start time.Time
	count int
}

// RateLimiter counts requests per key within a fixed time window.
type RateLimiter struct {
	mu       sync.Mutex
	windows  map[string]*window
	window   time.Duration
	capacity int
}

// NewRateLimiter builds a limiter allowing `capacity` requests per `windowDur`.
func NewRateLimiter(capacity int, windowDur time.Duration) *RateLimiter {
	return &RateLimiter{
		windows:  make(map[string]*window),
		window:   windowDur,
		capacity: capacity,
	}
}

// allowed reports whether a request under `key` may proceed.
func (rl *RateLimiter) allowed(key string) bool {
	rl.mu.Lock()
	defer rl.mu.Unlock()
	now := time.Now()
	w := rl.windows[key]
	if w == nil || now.Sub(w.start) >= rl.window {
		rl.windows[key] = &window{start: now, count: 1}
		return true
	}
	w.count++
	return w.count <= rl.capacity
}

// prune drops expired windows so the map cannot grow without bound. It runs
// opportunistically; a rare stale entry is harmless.
func (rl *RateLimiter) prune() {
	rl.mu.Lock()
	defer rl.mu.Unlock()
	now := time.Now()
	for k, w := range rl.windows {
		if now.Sub(w.start) >= rl.window*2 {
			delete(rl.windows, k)
		}
	}
}
