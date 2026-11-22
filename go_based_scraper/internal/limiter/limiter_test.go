package limiter

import (
	"errors"
	"sync"
	"testing"
	"time"
)

// fakeClock is a controllable time source for deterministic tests.
type fakeClock struct {
	mu sync.Mutex
	t  time.Time
}

func (c *fakeClock) now() time.Time {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.t
}

func (c *fakeClock) advance(d time.Duration) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.t = c.t.Add(d)
}

func TestAcquireBasic(t *testing.T) {
	clock := &fakeClock{t: time.Date(2026, 11, 17, 12, 0, 0, 0, time.UTC)}
	l := New(30, 1000, time.Minute, WithClock(clock.now))

	for i := 0; i < 30; i++ {
		if err := l.Acquire(); err != nil {
			t.Fatalf("acquire %d: %v", i, err)
		}
	}
	if got := l.DailyCount(); got != 30 {
		t.Errorf("DailyCount = %d, want 30", got)
	}
}

func TestRPMBlocksThenFrees(t *testing.T) {
	clock := &fakeClock{t: time.Date(2026, 11, 17, 12, 0, 0, 0, time.UTC)}
	l := New(2, 100, 10*time.Second, WithClock(clock.now))

	if err := l.Acquire(); err != nil {
		t.Fatal(err)
	}
	if err := l.Acquire(); err != nil {
		t.Fatal(err)
	}
	// Third should block until the oldest hits expires (10s).
	done := make(chan error, 1)
	go func() { done <- l.Acquire() }()
	clock.advance(10 * time.Second)
	select {
	case err := <-done:
		if err != nil {
			t.Errorf("Acquire after wait: %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("Acquire did not resume after window elapsed")
	}
}

func TestDailyCap(t *testing.T) {
	clock := &fakeClock{t: time.Date(2026, 11, 17, 12, 0, 0, 0, time.UTC)}
	l := New(100, 3, 0, WithClock(clock.now))

	for i := 0; i < 3; i++ {
		if err := l.Acquire(); err != nil {
			t.Fatalf("acquire %d: %v", i, err)
		}
	}
	if err := l.Acquire(); !errors.Is(err, ErrDailyExhausted) {
		t.Errorf("expected ErrDailyExhausted, got %v", err)
	}
}

func TestDailyReset(t *testing.T) {
	start := time.Date(2026, 11, 17, 23, 59, 59, 0, time.UTC)
	clock := &fakeClock{t: start}
	l := New(100, 2, 0, WithClock(clock.now))

	if err := l.Acquire(); err != nil {
		t.Fatal(err)
	}
	if err := l.Acquire(); err != nil {
		t.Fatal(err)
	}
	if err := l.Acquire(); !errors.Is(err, ErrDailyExhausted) {
		t.Errorf("expected exhausted before midnight, got %v", err)
	}
	// Cross midnight -> new day, counters reset.
	clock.advance(2 * time.Minute)
	if err := l.Acquire(); err != nil {
		t.Errorf("Acquire after day reset: %v", err)
	}
	if got := l.DailyCount(); got != 1 {
		t.Errorf("DailyCount after reset = %d, want 1", got)
	}
}

func TestRelease(t *testing.T) {
	clock := &fakeClock{t: time.Date(2026, 11, 17, 12, 0, 0, 0, time.UTC)}
	l := New(100, 2, 0, WithClock(clock.now))

	if err := l.Acquire(); err != nil {
		t.Fatal(err)
	}
	l.Release()
	if got := l.DailyCount(); got != 0 {
		t.Errorf("DailyCount after release = %d, want 0", got)
	}
	// Now the cap allows 2 again.
	if err := l.Acquire(); err != nil {
		t.Fatal(err)
	}
	if err := l.Acquire(); err != nil {
		t.Fatal(err)
	}
}

func TestConcurrentAcquireRespectsCap(t *testing.T) {
	clock := &fakeClock{t: time.Date(2026, 11, 17, 12, 0, 0, 0, time.UTC)}
	l := New(1000, 50, 0, WithClock(clock.now))

	var wg sync.WaitGroup
	var ok int64
	var mu sync.Mutex
	const goroutines = 200
	for i := 0; i < goroutines; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if err := l.Acquire(); err == nil {
				mu.Lock()
				ok++
				mu.Unlock()
			}
		}()
	}
	wg.Wait()
	if ok != 50 {
		t.Errorf("successful acquires = %d, want exactly 50", ok)
	}
	if got := l.DailyCount(); got != 50 {
		t.Errorf("DailyCount = %d, want 50", got)
	}
}
