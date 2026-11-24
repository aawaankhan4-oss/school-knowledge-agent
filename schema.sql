-- One row per source document (a PDF or a video)
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY,
    title TEXT,
    type TEXT,          -- 'pdf' or 'video'
    origin_path TEXT,   -- original local file path (kept even after cloud upload, so re-dropping the same file is still recognized)
    added_at TEXT,
    cloud_key TEXT,      -- set once the original file has been uploaded to cloud storage and deleted locally; NULL means it's still (or only ever was) local
    source_lastmod TEXT  -- web sources only: the page's sitemap <lastmod>, used to detect when it's changed and needs re-ingesting
);

-- One row per chunk of text extracted from a source
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    source_id INTEGER REFERENCES sources(id),
    chunk_index INTEGER,   -- order within the source
    text TEXT,
    start_time REAL,       -- for video transcripts only (seconds); NULL for PDFs
    end_time REAL,
    page_number INTEGER    -- for PDFs only; NULL for video
);

-- Full-text search index over the chunk text
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text, content='chunks', content_rowid='id');

-- Embedding vector per chunk, for semantic (meaning-based) search
CREATE TABLE IF NOT EXISTS chunk_embeddings (
    chunk_id INTEGER PRIMARY KEY REFERENCES chunks(id),
    embedding BLOB NOT NULL
);

-- Structured term dates and public holidays, parsed straight from the
-- school's own calendar page (see calendar_sync.py) rather than relying on
-- chunk search over a wall of dates. Replaced wholesale on every sync.
CREATE TABLE IF NOT EXISTS calendar_events (
    id INTEGER PRIMARY KEY,
    category TEXT,      -- e.g. 'Autumn Term', 'Public and School Holidays'
    event_name TEXT,
    start_date TEXT,     -- ISO date, e.g. '2026-10-01'
    end_date TEXT,       -- same as start_date for a single-day event
    note TEXT,           -- optional extra detail, e.g. 'students stay home'
    source_url TEXT
);

-- One row: tracks the calendar page's sitemap <lastmod>, so it's only
-- re-fetched and re-parsed when the school's site actually changes it.
CREATE TABLE IF NOT EXISTS calendar_sync_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    source_url TEXT,
    lastmod TEXT,
    synced_at TEXT
);

-- One row per person who can log in.
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    is_admin INTEGER DEFAULT 0,
    created_at TEXT
);

-- One row per question asked, for a lightweight admin view into what
-- people are actually asking. No answer text is stored — just enough to
-- see usage, who asked, whether the web fallback was used, and whether the
-- scope guard declined it (and why).
CREATE TABLE IF NOT EXISTS question_log (
    id INTEGER PRIMARY KEY,
    question TEXT,
    used_web INTEGER,      -- 0 or 1
    asked_at TEXT,
    user_id INTEGER REFERENCES users(id),
    blocked INTEGER DEFAULT 0,   -- 1 if the scope guard declined this question
    block_reason TEXT,           -- 'OFFTOPIC' or 'NEGATIVE', set only when blocked
    feedback TEXT,               -- 'up', 'down', or NULL if no feedback given
    retried_from INTEGER REFERENCES question_log(id)  -- set when this row is an automatic retry after a 👎 on an earlier answer
);
