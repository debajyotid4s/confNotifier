# Call4Paper — Android App

Kotlin + Compose scaffold for the BD Conference Tracker user-end.

## Quick start (Android Studio)

1. Open `Call4Paper/` in **Android Studio** (Ladybug+)
2. Add `app/google-services.json` (Firebase console → Project → Android app `com.call4paper.app`)
3. **Sync** Gradle (uses `gradle/libs.versions.toml` — Hilt, Room, Retrofit, Compose BOM, Firebase, Coil, Calendar)
4. Run on emulator / physical device (minSdk 24, target 35)

```text
Call4Paper/
  gradle/libs.versions.toml  — single source for Kotlin/AGP/Compose/Hilt/Room/Retrofit/OkHttp/Firebase versions
  app/build.gradle.kts       — compose + hilt + ksp + room + datastore + work + firebase
  app/src/main/              — MainActivity (Compose scaffold), Call4PaperApp (Hilt), theme, FCM service
```

### What’s wired
- **Hilt** (`Call4PaperApp`), **Compose Material3**, **SplashScreen**, **Navigation Compose** ready
- **FCM** `Call4PaperMessagingService` with 3 channels (`deadline_change` → HIGH / `conference` → DEFAULT / `daily_digest` → LOW) + deep link `call4paper://conference/open`
- **Room** `ConferenceEntity`, **Retrofit** `ConferenceDto` (submission deadlines only — matches `../scraper/schema.py:SUBMISSION_TYPES`)

### Next (per `../ANDROID_APP_PLAN.md`)
- FastAPI `api/` with `GET /conferences` (reuse `SUBMISSION_TYPES`), Firebase ID-token auth, FCM fanout
- `:core:designsystem` + `:feature:*` modules, Paging 3 + DataStore prefs, calendar (kizitonwose)

No secrets are committed — `google-services.json` stays local (already in `.gitignore`).
