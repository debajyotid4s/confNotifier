# scraper-reshaped — JS / Node.js Architectural Reshape

This directory is the staging area for the 100% JS/TS rebuild of `scraper/` (see plan: scraper-js shadow run).

- **Source of truth for new code:** all Node.js / TypeScript reshaped modules will live here (`scraper-reshaped/src/...`) on branch `js-reshaped`.
- **Python `scraper/` stays untouched on `main`** until shadow diff = 0 for 14 days — no prod switch until then.
- **Stack target:** Node 20 + TypeScript + `playwright` + `pg` + `openai` compat (see earlier mapping), `vitest` fixtures ported from `tests/test_patterns.py` etc.

Structure (to be filled):
```
scraper-reshaped/
├── src/db/{connection.ts,seenLinks.ts,conferences.ts}
├── src/browser.ts
├── src/patterns.ts
├── src/extraction/{rateLimiter.ts,jsonRepair.ts,client.ts}
└── tests/
```

Branch: `js-reshaped` (created from `main` @ 44576a9). Push with `git push -u origin js-reshaped`.
