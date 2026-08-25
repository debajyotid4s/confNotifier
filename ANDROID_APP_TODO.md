# Call4Paper Android App — Deferred Work & Notes

> **Status: documentation only.** No code under `Call4Paper/` was changed in this
> release, per the freeze. Everything below is a note for the next app cycle.
>
> Backend API reviewed against: `api/` at v0.3.0.

---

## 1. Compatibility with the v0.3.0 backend

**The v0.3.0 API is fully backward-compatible with the current app. No change is
required for the app to keep working.** Verified contract-by-contract:

| Contract | Status | Notes |
|---|---|---|
| `GET /conferences/upcoming` pagination | unchanged | Now paginates over *conferences* instead of deadline rows. The old behaviour could return the same conference twice in one page; the app never relied on that. |
| `GET /conferences/{id}` `bookmarked` field | unchanged | Still `null` when anonymous, `true/false` when signed in. |
| `status` field (`upcoming` / `past` / `null`) | unchanged | Same derivation from the soonest deadline. |
| FCM `data` keys (`type`, `screen`, `conference_id`) | unchanged | Values still `daily_digest`, `deadline_change`, `reminder`; screens `calendar`, `upcoming`. |
| Auth flow (Google/Firebase → JWT → `Authorization: Bearer`) | unchanged | |

New things the app will simply benefit from, with zero work:

- **gzip** is now enabled server-side — OkHttp already sends `Accept-Encoding: gzip`, so list payloads shrink substantially on mobile data.
- **Security headers** were added; they are no-ops for a native client.
- **Dead FCM tokens are pruned automatically** after failed sends, so the app no longer needs to proactively re-register tokens after reinstalls to "fix" notifications.
- `/health` no longer exposes which backing service is down.

---

## 2. Behaviour changes worth knowing (no action required)

### 2.1 Public read rate limit

Unauthenticated reads are now limited to **60 requests/min per IP**
(`api/deps.py`). A 429 response looks like:

```json
{ "detail": "Too many requests — try again later" }
```

The app's Room cache with TTL-based refresh already keeps it well below this in
normal use. If you ever add pull-to-refresh loops or prefetch-all-pages logic,
respect `Retry-After` semantics by backoff-and-retry rather than hammering.

### 2.2 Cache sharing across users

Conference detail responses are now cached once per conference (user-agnostic),
with the `bookmarked` flag layered on per request. Users see identical payloads;
nothing to do in the app.

---

## 3. Recommended app work, next cycle (priority order)

### 3.1 Handle the multi-target notification payload properly *(high)*

When several bookmarked deadlines land at once, the push carries
`{"type": "deadline_change", "screen": "upcoming"}` **without** a
`conference_id`. When exactly one deadline triggers, `conference_id` **is**
present and the screen is `calendar`.

Check `Call4PaperMessagingService.kt`: confirm the deep-link intent handles both
shapes — tapping a multi-deadline digest should open Upcoming, tapping a
single-deadline alert should open that conference's detail via `conference_id`.
If it currently assumes `conference_id` always exists, single-alerts deep-link
and digests crash or fall through.

### 3.2 Stop treating notification absence as token loss *(medium)*

Historically the app may have re-uploaded the FCM token on every cold start to
work around stale-token delivery failures. The backend now prunes dead tokens
itself (`_prune_dead_tokens` in `api/routers/internal.py`) and returns 409 if a
token is claimed by another account. Re-registering every launch is wasted
traffic; register on token rotation (`onNewToken`) and after login only.

### 3.3 Surface the strikethrough data the backend now provides *(medium)*

`conference_deadlines.deadline_previous` is now populated end-to-end (the scraper
used to write it only to the wide column). The Telegram channel shows
"~~Aug 15~~ → Sep 30 📝" but the app has no UI for it. Consider showing a small
"extended" chip + previous date on the conference detail screen — the data is
already flowing into `abstract_deadline_previous` / child-table rows; expose it
in the API contract first (`previous_abstract_deadline` etc.) before building UI.

### 3.4 Offline-first polish *(low)*

- `NetworkMonitor.kt` exists but screens should state clearly whether content is
  from cache ("updated X ago") vs live.
- Calendar month fetches are cached server-side for 5 min; aggressive
  month-flipping can rely on Room without staleness worry.

### 3.5 Longer-term items carried over from README future-work *(someday)*

Bengali localization, deadline countdown widget, submission tracker, conference
comparison view, iOS companion.

---

## 4. API-side notes that affect future app versions

Recorded here so the next API change doesn't surprise the app team:

1. **`DELETE /me/devices/{token}` puts an FCM token in the URL path.** Tokens end
   up in proxy/access logs. Not urgent, but the next breaking API version should
   move this to a request body (`POST /me/devices/delete`) or use the token id.
   Keep the path variant until the minimum supported app version exceeds it.
2. **JWTs expire after 7 days with no refresh endpoint.** The app silently fails
   auth after a week of non-use and the user must re-login. A `/auth/refresh`
   (or sliding expiry) would remove the most common "app logged me out" report.
3. **Rate limit headers are not sent yet** (`X-RateLimit-*`, `Retry-After`). Add
   them server-side before any app feature that polls.
