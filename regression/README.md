# Scraper regression dataset

Behavior-preserving fixtures for the Python → Go scraper migration. The
objective is **operational parity**: the Go scraper must reproduce the Python
scraper's *decisions*, not just its final rows. Two different mistakes can
produce superficially identical output, so we compare the **decisions that led
to the rows**, plus extraction cost (LLM requests) and processing time.

## The eight canonical cases

Each case in `fixtures.json` maps to one of the behaviors the migration must
preserve:

| # | Case | What it exercises |
|---|------|-------------------|
| 1 | Both submission deadlines | Successful extraction with `abstract` + `full_paper` deadlines; `insert`. |
| 2 | Abstract deadline only | Extraction with a single deadline type; `insert`. |
| 3 | No announced deadlines | TBA / "to be announced" page; still `insert` but no deadline rows; `tba` content flag. |
| 4 | Submission deadline extended | Deadline change detection; `update` with `deadline_previous` preserved. |
| 5 | New edition under a different URL | Duplicate-edition merge across URLs; `merge` into existing conference. |
| 6 | Website changes its CFP URL structure | New CFP path on the same host; discovery + re-discovery behavior. |
| 7 | False positive (ordinary event) | `is_conference=false` rejection; **no LLM cost** if caught by precheck, else `NotConference`. |
| 8 | Stale conference from a previous year | `stale_year` / `PastConference` skip; no insert, no wasted extraction. |

## Fixture format

`fixtures.json` is an array. Each entry:

```jsonc
{
  "id": "case_01_both_deadlines",
  "summary": "...",
  "input": {
    "url": "https://example.ac.bd/cfp/2027/",
    "page_text": "representative page content the extractor sees",
    // prior DB state for this website, if any (drives insert vs update vs merge)
    "prior_db": {
      "exists": false,
      "conference_id": 0,
      "website": null,
      "title": null,
      "date_start": null,
      "deadlines": []
    }
  },
  "expected": {
    "accepted": true,
    "reject_reason": null,          // NotConference | LowConfidence | PastConference
                                          // | StaleURL | InvalidPermanent | DuplicateURL | AlreadyDecided
    "title": "...",
    "submission_dates": { "abstract": null, "full_paper": null },
    "edition_identity": { "website": "...", "title": "...", "date_start": null },
    "db_decision": "insert",        // insert | update | merge | skip
    "duplicate": false,
    "retry": false,
    "deadline_change": null         // { type, from, to } when a deadline moved
  },
  "cost": { "llm_requests": 1 }     // LLM calls this case should consume
}
```

`reject_reason`, `db_decision`, `duplicate`, `retry`, and `deadline_change`
are the decision dimensions the shadow comparison checks. `cost.llm_requests`
guards against the Go implementation quietly spending more extraction budget.

## How to run

Two layers:

### Layer 1 — deterministic decisions (offline, no LLM, no browser)

Classification (`conf.ClassifyLink`), stale detection, dedup
(`FindByUrl` / `ByEdition`), insert-vs-update, retry, and deadline-change
detection are pure logic. `compare.go` (run via `go test`) loads
`fixtures.json` and asserts the Go pipeline produces the expected decision for
each case against an in-memory / test-DB conference index.

```bash
cd go_based_scraper
go test ./internal/pipeline/ -run TestRegressionFixtures -tags integration -v
```

### Layer 2 — live shadow comparison (needs prod DB access + keys)

Run the Python and Go scrapers against equivalent source inputs **without
letting both write production data**, then diff their JSON outputs:

```bash
./regression/compare.sh --python --go --out shadow_run_1.json
```

`compare.sh` runs each implementation in dry-run against the same seed URLs,
emits per-decision JSON, and diffs them. See the script for the exact flags.

## Population status

`fixtures.json` holds the eight cases with representative inputs and the
**expected** decisions derived from the Python reference semantics. Values
marked `"pending"` must be confirmed against a live Python run before the
fixtures are frozen as the parity oracle. Layer 1 assertions pass now; Layer 2
requires the shadow-run data described in the migration plan.
