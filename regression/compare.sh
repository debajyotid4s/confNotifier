#!/usr/bin/env bash
#
# Layer 2 shadow comparison — run the Python and Go scrapers against the same
# seed inputs and diff their per-decision JSON. This is the live-parity half of
# the regression suite; it needs production DB access and the extraction keys,
# and it must NOT let both implementations write production data.
#
# Usage:
#   ./regression/compare.sh [--python] [--go] [--seeds N] [--out FILE]
#
#   --python        Run the Python scraper (dry-run) and write its decisions.
#   --go            Run the Go scraper (dry-run) and write its decisions.
#   --both          Run both (default).
#   --seeds N       Number of seed URLs to draw from the regression corpus.
#   --out FILE      Output directory for the JSON artifacts (default: ./shadow).
#
# Prerequisites (export before running):
#   DATABASE_URL      production DSN
#   GOOGLE_AI_KEY[23] extraction keys
#   TELEGRAM_*        notification config (suppresses posts when unset)
#
# The scrapers run with --dry-run so they only READ and classify; nothing is
# written to the production DB and no Telegram posts are sent.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

SEEDS=8
OUT="./shadow"
RUN_PYTHON=0
RUN_GO=0

usage() { grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --python) RUN_PYTHON=1 ;;
    --go)     RUN_GO=1 ;;
    --both)   RUN_PYTHON=1; RUN_GO=1 ;;
    --seeds)  SEEDS="$2"; shift ;;
    --out)    OUT="$2"; shift ;;
    -h|--help) usage 0 ;;
    *) echo "unknown arg: $1"; usage 1 ;;
  esac
  shift
done

[[ $RUN_PYTHON -eq 0 && $RUN_GO -eq 0 ]] && RUN_PYTHON=1 && RUN_GO=1
mkdir -p "$OUT"

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "SKIP: DATABASE_URL not set — Layer 2 needs prod DB access." >&2
  echo "      Layer 1 (offline fixtures) already covers the deterministic spine." >&2
  exit 0
fi

seed_urls() {
  # Draw seed URLs from the regression corpus (regression/fixtures.json).
  python3 - "$SEEDS" <<'PY'
import json, sys
n = int(sys.argv[1])
fx = json.load(open("regression/fixtures.json"))
for c in fx[:n]:
    print(c["input"]["url"])
PY
}

run_python() {
  local out="$OUT/python_decisions.json"
  echo ">> Python scraper (dry-run) -> $out"
  local urls; urls="$(seed_urls)"
  # Dry run: discovery + classification only, no DB writes, no Telegram posts.
  PYTHONPATH="$REPO_ROOT" DATABASE_URL="$DATABASE_URL" \
    GOOGLE_AI_KEY="${GOOGLE_AI_KEY:-}" GOOGLE_AI_KEY_2="${GOOGLE_AI_KEY_2:-}" \
    GOOGLE_AI_KEY_3="${GOOGLE_AI_KEY_3:-}" \
    python3 "$REPO_ROOT/scraper/main.py" --dry-run <<<"$urls" > "$out" 2>&1 || true
}

run_go() {
  local out="$OUT/go_decisions.json"
  echo ">> Go scraper (dry-run) -> $out"
  local urls; urls="$(seed_urls)"
  # Dry run: discovery + classification only, no DB writes, no Telegram posts.
  ( cd "$REPO_ROOT/go_based_scraper" && \
    DATABASE_URL="$DATABASE_URL" OPENAI_API_KEY="${OPENAI_API_KEY:-}" \
    go run . scrape --dry-run <<<"$urls" > "$out" 2>&1 || true )
}

diff_decisions() {
  local a="$OUT/python_decisions.json" b="$OUT/go_decisions.json"
  echo ">> Diffing $a vs $b"
  if [[ ! -f "$a" || ! -f "$b" ]]; then
    echo "SKIP: both artifacts must exist to diff." >&2
    return 0
  fi
  # Per-decision diff on the normalized (url, decision) tuples.
  python3 - "$a" "$b" <<'PY'
import json, sys
def load(p):
    try:
        return json.load(open(p))
    except Exception:
        return []
a = load(sys.argv[1]); b = load(sys.argv[2])
# Normalize to {url: decision} when the artifacts are decision lists.
def norm(x):
    d = {}
    for r in x:
        if isinstance(r, dict):
            d.setdefault(r.get("url", r.get("input", "")), r.get("decision", r.get("outcome", "")))
    return d
na, nb = norm(a), norm(b)
keys = sorted(set(na) | set(nb))
mismatch = 0
for k in keys:
    da, db = na.get(k), nb.get(k)
    if da != db:
        mismatch += 1
        print(f"  DIFF {k}: python={da} go={db}")
print(f"  compared {len(keys)} URLs; {mismatch} decision mismatch(es)")
sys.exit(1 if mismatch else 0)
PY
}

$([ $RUN_PYTHON -eq 1 ] && echo run_python)
$([ $RUN_GO -eq 1 ] && echo run_go)
diff_decisions
