-- Add additional user details for analytics and device tracking
ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_model TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS ip_address TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS user_agent TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS device_info TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_ip TEXT;
