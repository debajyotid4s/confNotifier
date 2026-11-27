# Scraper cutover plan: Python → Go

Operational procedure for replacing the Python scraper with the Go scraper as
the sole production writer. Follow the steps in order; do not skip the shadow
phase. The guiding principle: **preserve behavior, prove parity, then switch.**

Prerequisite: Step 1 (reference tag + snapshot) and Step 2 (P0 hardening +
regression dataset) are complete. The edition-merge gap identified in the
regression review must be fixed before cutover (see below).

---

## Step 3 — Shadow testing (read-only, no production writes)

Goal: prove Go reproduces Python's **decisions**, then its rows.

1. Stand up a **separate testing database** (or use dry-run against prod with
   writes disabled). Neither implementation writes production data during shadow.
2. Seed both scrapers with the **same source inputs** (the regression corpus in
   `regression/fixtures.json` plus a representative live URL set).
3. Run each implementation and capture, per candidate:
   - discovered URLs
   - accepted / rejected (and the reason)
   - extracted title
   - submission dates
   - conference edition identity
   - **insert vs update vs merge decision**
   - duplicate-detection result
   - retry vs terminal decision
   - deadline changes (and `deadline_previous` preservation)
   - **extraction cost** (LLM request count) and processing time
4. Diff the two decision streams (`regression/compare.sh`). Every **material**
   discrepancy must be explained and resolved.
5. **Acceptance condition:** Go demonstrates it preserves Python's important
   behavior across the regression set and real-world shadow runs, with every
   material discrepancy explained.

> Compare **decisions, not just final rows.** Two different mistakes can produce
> superficially identical output (e.g. a wrong insert vs a wrong update both
> yield a row with the same title).

### Resource budget
Treat the 1000/day (RPD) and 30 RPM limits as an **explicit budget**, not an
incidental constraint. Record Go's per-run LLM cost in shadow and confirm it does
not quietly exceed Python's. If Go is more chatty, cut candidate scope before
raising the quota.

### Split the schedule by cost/frequency
Do **not** blindly copy Python's five runs/day. Separate:
- broad certificate-transparency sweeps (low frequency)
- incremental discovery (medium)
- pending / retryable extraction (medium-high)
- deadline verification (medium)
- notification delivery (as needed)

Each has a different operational cost; run each at the frequency it needs. A
persisted queue + checkpoint mechanism becomes valuable as coverage grows.

---

## Step 4 — Make Go the sole production writer

1. Complete Step 3 shadow testing to acceptance.
2. Fix the edition-merge gap so Go's dedup matches Python's edition identity
   (`title-acronym + year`), not URL-only. **Do not skip.**
3. Run a **full Go production scrape with writes enabled** (manual dispatch,
   `cancel-in-progress: false`).
4. Verify all DB updates and Telegram notifications landed correctly.
5. **Disable the Python schedule** (pause the `scraper.yml` cron).
6. **Enable the Go schedule** at the split frequencies from Step 3.
7. **Observe Go as the sole production writer** for a sustained window (at least
   one full weekly cycle, covering all scheduled run types).

Keep `cancel-in-progress: false` on the Go scrape job: cancelling a run
halfway can leave confusing operational state even though individual DB ops are
idempotent.

### Rollback
The `python-scraper-known-good` Git tag and the migrated Python code remain as
rollback. If Go shows material regressions during observation, re-enable the
Python schedule; both can coexist briefly behind the same DB.

---

## Step 5 — Retire Python scraper

Only after Go has demonstrated stable operation as the sole writer:

- Remove the Python scheduled workflow (`scraper.yml` cron job / file).
- Remove scraper deployment dependencies no longer used by Go.
- Remove obsolete Python scraper modules.
- Remove redundant configuration files superseded by Go.
- Remove Python-specific CI jobs that no longer apply.
- **Preserve migration notes and historical release information.**
- Git history + the `python-scraper-known-good` tag preserve the old
  implementation — no need to keep duplicate code "just in case."
