# School Info Assistant

A standalone copy of the `rag-knowledge-agent` chatbot, adapted for a school: it answers questions strictly from the school's own handbooks, policies, slides, videos, and crawled website pages — there's no live web search, so if something isn't covered by the school's own material, it says so honestly instead of answering from the open internet.

This is a fully independent project (its own database, its own login) that can run at the same time as the original.

## Running it

```
.\venv\Scripts\python.exe app.py
```

Then open **http://127.0.0.1:5001** (note the different port — `5001`, not `5000`, so it doesn't clash with the original if both are running).

**Accounts:** anyone can create their own account from the **Create one** link on the sign-in page — no admin approval needed. The original shared password still works too, under the username `admin` (it was migrated into a real account automatically the first time the app started after accounts were added), and that account is the one with access to `/admin`. New accounts signed up afterward are regular (non-admin) users.

To make another account an admin, run:
```
.\venv\Scripts\python.exe -c "import sqlite3; sqlite3.connect('db/knowledge.db').execute(\"UPDATE users SET is_admin = 1 WHERE username = 'their-username'\").connection.commit()"
```

## Adding content

Drop files into the matching folder and they're ingested automatically (no command needed, as long as `app.py` is running):

| Folder | Accepts |
|---|---|
| `pdfs/` | `.pdf` (scanned pages are OCR'd automatically) |
| `videos/` | `.mp4`, `.mov`, `.mkv`, `.avi`, `.wmv`, `.flv`, `.webm`, `.mp3`, `.wav`, `.m4a`, `.ogg`, `.flac` |
| `documents/` | `.docx`, `.pptx`, `.txt`, `.md` |

Good things to add for a school: the student/parent handbook, the school calendar, enrollment and attendance policies, a recording of a back-to-school-night presentation, board meeting minutes, sports/extracurricular schedules.

## Adding the school's website

Unlike the folders above, the school's own website isn't something the watcher can pick up automatically — there's no local file to notice. Instead, run:

```
.\venv\Scripts\python.exe ingest_web.py
```

This reads `SITEMAP_URL` from `.env` (the school website's sitemap index — usually `https://[domain]/sitemap.xml` or `https://[domain]/sitemap_index.xml`, findable via the site's `robots.txt`), crawls every page it lists, and ingests each one's visible text the same way a document is ingested. Pages already in the database are skipped by URL, so it's safe to re-run any time the site changes — only new or previously-failed pages are fetched again.

A few sitemap sections are skipped by default (`category-sitemap`, `author-sitemap`, `post-sitemap` — the last being the news/blog feed, often hundreds of time-sensitive articles rather than reference info); edit `EXCLUDE_SITEMAP_PATTERNS` at the top of `ingest_web.py` to change that.

If cloud storage is configured, a text snapshot of each crawled page is archived to the bucket too, so the knowledge base keeps a record even if the live page later changes or is taken down.

## Deploying it publicly (Fly.io)

Running it locally (above) only works for people on the same machine or Wi-Fi network. To get a real public URL reachable from anywhere, the project is set up to deploy to [Fly.io](https://fly.io) as a Docker container (`Dockerfile`, `fly.toml` are already in this folder) — chosen specifically because it deploys straight from this local folder with its own CLI, without needing a GitHub repo (this machine doesn't have `git` installed).

**This is a real decision, not just a config change**: it means creating a Fly.io account (with a payment method — a small instance kept always-on, which this needs for reliable startup speed, isn't free), and copying your API keys into Fly's own secrets store. Do this deliberately, not as a reflex.

1. **Install the Fly CLI** (`flyctl`) — see [fly.io/docs/flyctl/install](https://fly.io/docs/flyctl/install/) for the current Windows install command.
2. **Sign up / log in**: `fly auth login` — opens a browser to sign in or create an account.
3. **Launch the app** from this folder: `fly launch --no-deploy` — it reads `fly.toml`, will ask you to confirm or change the app name (must be globally unique across all of Fly, so `school-info-assistant` will likely need a suffix) and region, and will offer to create the persistent volume defined in `fly.toml` — say yes.
4. **Copy your secrets across** — one `fly secrets set` per line in your `.env` file:
   ```
   fly secrets set GROQ_API_KEY=... SECRET_KEY=... APP_PASSWORD_HASH=... B2_KEY_ID=... B2_APPLICATION_KEY=... B2_BUCKET_NAME=... B2_ENDPOINT=... SITEMAP_URL=... CALENDAR_URL=... CALENDAR_SITEMAP_URL=...
   ```
   (copy the actual values from `.env` — never commit that file or paste real keys into a chat or a public place)
5. **Deploy**: `fly deploy` — builds the Docker image and ships it. First deploy starts with an empty database (same fresh-install experience as running it locally for the first time) — run `ingest_web.py`-equivalent ingestion against it, or see the next step to bring your existing data instead.
6. **Bring your existing knowledge base across** (recommended, so you don't re-crawl everything from scratch): `fly ssh sftp shell`, then `put db/knowledge.db /app/db/knowledge.db` to upload your local database onto the persistent volume, then `fly apps restart` to pick it up.

After that, `fly deploy` from this folder re-deploys any future code changes, and the persistent volume means the database (search index, accounts, calendar, question log) survives every redeploy.

## What's shared with the original project

- Same Groq API key (reused from `rag-knowledge-agent`'s `.env` — same account, no new signup needed)
- Same Python packages (the `venv` folder was copied, not reinstalled, to skip re-downloading ~2GB of ML packages)
- Mostly the same backend code — branding (title, colors, copy, starter questions) and the system prompt (tuned to answer as a school assistant) differ, and this copy's `ask.py` has no live web search at all (see Phase 19 in `PROGRESS.md`), unlike the original project

## What's different (own to this copy)

- Its own SQLite database (`db/knowledge.db`) — starts empty, has no connection to the original project's data
- Its own accounts, login, and Flask secret key
- Runs on port `5001` instead of `5000`
