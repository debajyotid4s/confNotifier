-- Phase 1: additive tables on existing Neon DB. Do not touch conferences.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  google_subject_id TEXT UNIQUE NOT NULL,
  email TEXT UNIQUE NOT NULL,
  username TEXT UNIQUE NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bookmarks (
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  conference_id INTEGER NOT NULL REFERENCES conferences(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, conference_id)
);

CREATE TABLE IF NOT EXISTS device_tokens (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  fcm_token TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(fcm_token)
);

-- Ensure telegram_messages exists (added in scraper fix #4 — idempotent)
CREATE TABLE IF NOT EXISTS telegram_messages (
  id SERIAL PRIMARY KEY,
  website TEXT NOT NULL,
  message_id BIGINT NOT NULL,
  message_type TEXT NOT NULL,
  chat_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(website, message_id)
);
