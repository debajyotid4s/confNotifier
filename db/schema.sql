CREATE TABLE IF NOT EXISTS known_subdomains (
    id SERIAL PRIMARY KEY,
    subdomain TEXT NOT NULL UNIQUE,
    domain TEXT NOT NULL,
    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS seen_links (
    id SERIAL PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL DEFAULT 'unknown',
    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS conferences (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    date_start DATE,
    date_end DATE,
    city TEXT,
    country TEXT NOT NULL DEFAULT 'Bangladesh',
    website TEXT NOT NULL UNIQUE,
    organizer TEXT,
    category TEXT,
    confidence REAL NOT NULL DEFAULT 0.0,
    raw_source TEXT,
    is_notified BOOLEAN NOT NULL DEFAULT FALSE,
    notified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conferences_website ON conferences (website);
CREATE INDEX IF NOT EXISTS idx_conferences_date_start ON conferences (date_start);
CREATE INDEX IF NOT EXISTS idx_known_subdomains_subdomain ON known_subdomains (subdomain);
CREATE INDEX IF NOT EXISTS idx_seen_links_url ON seen_links (url);
