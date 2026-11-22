package discovery

import (
	"context"
	"os"
	"strings"
	"time"

	"github.com/chromedp/cdproto/cdp"
	"github.com/chromedp/cdproto/page"
	"github.com/chromedp/chromedp"
)

// browserTimeout bounds a full page-load+render cycle.
const browserTimeout = 60 * time.Second

// browserChallengeBudget bounds total time spent clearing a Cloudflare
// "confirm you are human" JS challenge before giving up.
const browserChallengeBudget = 45 * time.Second

// browserChallengePause is how long to wait between scroll nudges while the
// challenge tick resolves.
const browserChallengePause = 5 * time.Second

// BrowserFetcher is the most expensive transport tier: a headless Chrome that
// executes JavaScript, so it can read content a plain GET cannot see.
//
// It mirrors HTTPFetcher's single-method contract (fetch one URL → body or
// empty) so TieredProbe can treat it as just another escalation tier. This is
// the Go port of scraper/sources/special/probe.py's Playwright tier: requests
// and curl are tried first, and the browser only engages when a body is
// fetched but fails verification (or the cheap tiers yield nothing).
//
// Cloudflare "Confirm you are human" JS challenges are defeated the same way
// the Python scraper does it: a stealth context (navigator.webdriver hidden,
// chrome object, plugins, languages) plus a human-like scroll, which lets the
// tick/checkbox resolve on its own after a short wait.
type BrowserFetcher struct {
	// chromePath is the Chrome/Chromium binary; "" means auto-discover.
	chromePath string
}

// NewBrowserFetcher builds a headless-Chrome fetcher. chromePath may be empty,
// in which case the well-known system locations are searched.
func NewBrowserFetcher(chromePath string) *BrowserFetcher {
	if chromePath == "" {
		chromePath = discoverChrome()
	}
	return &BrowserFetcher{chromePath: chromePath}
}

// stealthInit patches the browser fingerprint so Cloudflare's JS challenge
// treats the page as a real desktop browser and resolves its "confirm you are
// human" tick automatically. Mirrors playwright_stealth in the Python scraper.
const stealthInit = `
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.navigator.chrome = {runtime: {}};
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
1;
`

// fetch navigates to url with a headless browser and returns the rendered text.
// It returns an empty string (never a hard error) when no browser is available
// or the page fails to render, so the caller can fall back to earlier tiers.
func (b *BrowserFetcher) fetch(ctx context.Context, url string) (string, error) {
	if b.chromePath == "" || !chromeExists(b.chromePath) {
		return "", nil
	}

	// execCtx allocates Chrome with stealth flags; ctx attaches a page session.
	execCtx, cancelExec := chromedp.NewExecAllocator(ctx,
		chromedp.Flag("disable-blink-features", "AutomationControlled"),
		chromedp.Flag("no-sandbox", true),
		chromedp.Flag("disable-dev-shm-usage", true),
		chromedp.Flag("disable-gpu", true),
		chromedp.Flag("window-size", "1920,1080"),
		chromedp.UserAgent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"),
	)
	defer cancelExec()

	ctx, cancel := chromedp.NewContext(execCtx)
	defer cancel()

	toCtx, cancelTo := context.WithTimeout(ctx, browserTimeout)
	defer cancelTo()

	// Inject the stealth script into every new document before navigation.
	if _, err := chromedp.Run(toCtx, injectStealth(toCtx)); err != nil {
		return "", nil
	}

	if _, err := chromedp.Run(toCtx, chromedp.Steps(
		chromedp.Navigate(url),
		chromedp.WaitReady(chromedp.CSS("body")),
	)); err != nil {
		return "", nil
	}

	// Cloudflare "confirm you are human" challenges auto-resolve after a short
	// wait; the stealth fingerprint + human scroll nudge it along. Retry a few
	// times, re-reading the body, until the challenge clears and the real page
	// loads, or the budget runs out.
	deadline := time.Now().Add(browserChallengeBudget)
	for {
		finalURL, _ := chromedp.Run[string](toCtx, chromedp.Evaluate[string](`location.href`))
		body, err := chromedp.Run[string](toCtx, chromedp.Evaluate[string](`document.documentElement.outerHTML`))
		if err != nil {
			return "", nil
		}
		// Challenge cleared AND we're past the challenge path → real page.
		if !isCloudflareChallenge(body) && !strings.Contains(finalURL, "__cf_chl") {
			text := sanitizeRendered(body)
			if len(text) > 50 {
				return text, nil
			}
			// Body present but short: wait for full render, then retry once.
			if _, werr := chromedp.Run(toCtx, chromedp.Steps(
				chromedp.WaitReady(chromedp.CSS("body")),
				chromedp.Sleep(3*time.Second),
			)); werr == nil {
				body, _ = chromedp.Run[string](toCtx, chromedp.Evaluate[string](`document.documentElement.outerHTML`))
				if len(sanitizeRendered(body)) > 50 {
					return sanitizeRendered(body), nil
				}
			}
		}
		if time.Now().After(deadline) {
			return "", nil
		}
		// Nudge: scroll twice and wait for the tick to resolve.
		if _, err := chromedp.Run(toCtx, chromedp.Steps(
			chromedp.Func(func(ctx context.Context, t *chromedp.Target) error {
				_, e := chromedp.Run(ctx, chromedp.Evaluate[any](humanScrollJS))
				return e
			}),
			chromedp.Sleep(browserChallengePause),
			chromedp.Func(func(ctx context.Context, t *chromedp.Target) error {
				_, e := chromedp.Run(ctx, chromedp.Evaluate[any](humanScrollJS))
				return e
			}),
			chromedp.Sleep(browserChallengePause),
		)); err != nil {
			return "", nil
		}
	}
}

// injectStealth returns an action that patches the browser fingerprint via
// page.addScriptToEvaluateOnNewDocument, attaching the CDP session first so the
// call succeeds. It degrades to a no-op (never a hard error) so a browser
// hiccup simply falls back to the earlier HTTP tiers.
func injectStealth(ctx context.Context) chromedp.Action[chromedp.Void] {
	return chromedp.Func(func(ctx context.Context, t *chromedp.Target) error {
		if _, stop := t.Subscribe(page.AddScriptToEvaluateOnNewDocument.Method); stop != nil {
			defer stop()
		}
		if _, err := cdp.Call(ctx, t, page.AddScriptToEvaluateOnNewDocument,
			page.AddScriptToEvaluateOnNewDocumentParams{Source: stealthInit, RunImmediately: ptrBool(true)}); err != nil {
			return err
		}
		return nil
	})
}

// humanScrollJS mimics a real user making small randomized scrolls with smooth
// behavior, which nudges Cloudflare's JS challenge to complete its "you are
// human" check. Mirrors scraper/browser/scroll.py::_human_like_scroll.
const humanScrollJS = `
(function() {
  for (var i = 0; i < 4; i++) {
    setTimeout(function() {
      window.scrollTo({top: Math.random() * 500, behavior: 'smooth'});
    }, i * 600);
  }
})();
1;
`

// cfChallengeSigs marks a Cloudflare "confirm you are human" challenge shell.
var cfChallengeSigs = []string{"challenge-form", "cf-challenge", "Just a moment", "__cf_chl", "__cfawvt", "cdn-cgi/challenge"}

// isCloudflareChallenge reports whether html is a Cloudflare JS challenge shell.
func isCloudflareChallenge(html string) bool {
	for _, sig := range cfChallengeSigs {
		if strings.Contains(html, sig) {
			return true
		}
	}
	return false
}

// sanitizeRendered strips tags/scripts from a browser-rendered body and trims.
func sanitizeRendered(html string) string {
	text := stripHTML(html)
	return strings.TrimSpace(text)
}

// ptrBool returns a pointer to b, for CDP bool params.
func ptrBool(b bool) *bool { return &b }

// chromeExists reports whether path is a readable executable file.
func chromeExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && !info.IsDir()
}

// discoverChrome searches common install locations for a usable Chrome binary.
func discoverChrome() string {
	candidates := []string{
		os.Getenv("BROWSER_PATH"),
		"/usr/bin/google-chrome",
		"/usr/bin/google-chrome-stable",
		"/usr/bin/chromium",
		"/usr/bin/chromium-browser",
		"/opt/google/chrome/chrome",
	}
	for _, c := range candidates {
		if c == "" {
			continue
		}
		if _, err := os.Stat(c); err == nil {
			return c
		}
	}
	return ""
}
