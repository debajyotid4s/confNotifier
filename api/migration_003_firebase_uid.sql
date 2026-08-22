-- Allow Firebase email/password users alongside Google users
ALTER TABLE users ADD COLUMN IF NOT EXISTS firebase_uid TEXT UNIQUE;
ALTER TABLE users ALTER COLUMN google_subject_id DROP NOT NULL;
-- google_subject_id is now nullable (Google users have it, Firebase users have firebase_uid)
-- email and username remain NOT NULL UNIQUE
