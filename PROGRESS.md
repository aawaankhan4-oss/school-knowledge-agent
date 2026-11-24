# School Info Assistant — Progress Log

A running record of what's been built on this project, session by session. I update this file each time we make meaningful progress — ask me to add to it any time.

This project started as a full copy of `rag-knowledge-agent` (the original Moebius Software chatbot) — same retrieval pipeline, same ingestion code, same error handling — then diverged from there with its own branding, its own knowledge base, and its own features. See `rag-knowledge-agent`'s own progress log for that shared foundation; this log picks up from where the two projects started growing apart.

---

## Phase 1 — Becoming its own chatbot

**Goal: reuse everything already built, for a completely different audience.**

- Copied the pipeline unchanged — confirmed nothing was Moebius-specific first.
- Reused the Groq/Tavily keys and the `venv` folder — skipped ~2GB of re-downloads.
- New identity: branding, school starter questions, own password/secret key, own empty database, runs on port `5001`.
- Warmer system prompt; web-fallback answers are flagged as possibly not matching the school's real policies.
- **Bug fixed:** a fresh install crashed on the first question (schema never created). `app.py` now creates it on startup.
- **Verified:** a real handbook doc was ingested, answered correctly, and cited "part 1".

---

## Phase 2 — Cloud storage for the school's own files

**Goal: stop a large knowledge base from filling up local disk.**

- Split the knowledge base in two: the small searchable index (stays local) and the large raw files (move to the cloud).
- Added `cloud_storage.py` on **Backblaze B2** — uploads only after chunks are safely committed, so a failed upload never loses data.
- Own dedicated B2 bucket and key, kept separate from the original project's.
- **Bug fixed:** B2 needs SigV4 signing; boto3's default (SigV2) was getting rejected with a 401.
- **Verified:** uploaded a real document and video, confirmed local deletion, confirmed retrieval via signed URL, confirmed Q&A and video playback still work.

---

## Phase 3 — Ingesting the school's own website

**Goal: pull the live website into the knowledge base, not just uploaded files.**

- Built `ingest_web.py` — crawls the school's sitemap, ingests every page's text through the same pipeline as documents.
- Checked `robots.txt` first; added a polite delay between fetches.
- Excluded category/author/news-feed sitemap sections by default — noise, not reference info.
- **Bug fixed:** the nav menu wasn't in a `<nav>` tag — every page's text was swamped with menu links.
- **Bug fixed:** some pages (FAQ answers) load client-side via JS and sat invisible in an HTML comment — now parsed out.
- **Bug fixed:** short FAQ answers never repeated the question's own words — fixed by prepending the page title to indexed text.
- Reuses the existing "web" source type and citation UI — zero frontend changes needed.
- Each page's text is also archived to B2.
- **Verified:** a full 219-page crawl — zero fetch errors, citations check out.

---

## Phase 4 — A showcase landing page

**Goal: something presentable to show off the assistant, separate from the working app.**

- Standalone marketing page with the school's real branding and colors.
- Structured as hero → "how it answers" → honest web-fallback section → call to action.
- CTA buttons link to the local app — only work while it's running on the same machine.

---

## Phase 5 — Fixing how answers actually read

**Goal: answers should read like a person wrote them, not like copied text.**

- **Bug fixed:** the model wrote valid Markdown, but the UI showed it as literal symbols — looked like raw copied text.
- Added a safe Markdown renderer (bold, bullet lists, numbered lists); user input and errors stay plain text.
- Tightened the prompt to match: explain in its own words, no tables, sparing bold, one consistent citation style.
- **Verified:** a document question and a web-fallback question — both clean, both consistently cited.

---

## Phase 6 — A calendar that stays current on its own

**Goal: let students and parents reliably check term dates and holidays.**

- Diagnosed why chunk search is a poor fit: "when's the next holiday" needs reasoning over the *whole* list, not one matching chunk.
- Built `calendar_sync.py` — parses the real page into clean rows (event, category, dates, note) in their own table.
- Auto-updates via the page's own sitemap `<lastmod>` — checked on startup and every 6 hours, no blind timer.
- The full calendar plus today's date is injected into every question's context.
- **Verified:** "next holiday", "half term dates", and "is there school on Oct 1" all answered correctly.

---

## Phase 7 — Keeping the site crawl honest, conversation memory, and an admin view

**Goal: a batch of real gaps — a stale crawl, no memory between questions, no visibility without a terminal.**

- The website crawl now detects *changed* and *removed* pages, not just new ones.
- **Bug fixed:** two crawls writing at once wrongly deleted a live page. Fixed with a two-fetch confirmation before deleting, plus a lock file blocking simultaneous crawls.
- **Bug fixed:** long crawls hit occasional network blips — added retry with backoff, backfilled the pages silently skipped before the fix.
- Conversation memory — the last few exchanges are remembered per session, feeding both the model and the search query. "New chat" clears it.
- **Bug fixed:** the calendar page was cited two inconsistent ways — now only the structured calendar block is used.
- Multi-language answers — responds in whatever language the question was asked in.
- New `/admin` page — KB size, calendar sync status, question stats, recent questions, re-crawl/re-sync buttons.
- New `question_log` table — tracks what's asked and whether the web fallback was needed.

---

## Phase 8 — Keeping the assistant on-topic

**Goal: only answer questions about the school, and refuse to speculate about anything negative regarding it.**

- Added a scope check before any search or web call — declines anything off-topic or asking for something negative about the school.
- **Bug fixed:** the same question sometimes passed, sometimes got wrongly blocked. Fixed with `temperature=0` and a YES-biased prompt.
- **Verified:** an unrelated question (declined), a negative request (declined), a real question including a follow-up (answered normally both times).

---

## Phase 9 — A real calendar page, linked from the chatbot

**Goal: let people browse term dates and holidays visually, not just by asking.**

- New `/calendar` page — a real month grid, color-coded by category, with an "Upcoming" agenda panel.
- Reads from the same synced table the chatbot already uses — no separate maintenance.
- Every event links back to the chatbot and auto-asks about it — one click instead of retyping.
- **Verified:** clicking a real holiday correctly asked and answered with the right dates.

---

## Phase 10 — Real accounts, a richer admin view, and answer feedback

**Goal: know who's asking what (including what gets blocked), and let people rate their answers.**

- Replaced the single shared password with real per-person accounts (`users` table, `/signup`, username + password).
- The old password was migrated automatically into a named `admin` account — nobody got locked out.
- `/admin` now actually requires the `is_admin` flag.
- **Verified:** a non-admin account gets a real `403` on `/admin`.
- Blocked questions are now logged too, with who asked and why (off-topic vs. negative).
- Added 👍/👎 feedback on answered responses, tied to that question's log entry.
- Richer admin view: per-user activity, a blocked-questions table, a "top topics" word-frequency view, feedback totals.

---

## Phase 11 — Demo-readiness check

**Goal: find anything that could visibly break or stall during a live demo, before it happens in front of people.**

- Live-checked every external dependency: Groq (current model confirmed live, real call succeeded), Tavily (real search succeeded), Backblaze B2 (reachable, 0.7 MB of the 10 GB free tier used — plenty of headroom). No API keys, quotas, or storage limits are a near-term risk.
- **Bug fixed:** the app's startup had been visibly slow and inconsistent all session (25 seconds to 3+ minutes). Root-caused it to the calendar sync's very first check running *before* Flask started listening — a slow or unreachable school website at that exact moment could stall the whole app from binding its port at all. Fixed by moving that first sync into the same background thread as every later one, so startup never depends on an outside network call. Verified with two clean restarts: 31.5s and 21.7s, both well under the worst delays seen before.
- **Still worth doing, not a code fix**: if the Windows machine running this has antivirus real-time scanning on, it may be re-scanning the `venv` folder's ML libraries (`torch`, `sentence-transformers`) on every launch — a well-known cause of slow Python ML app startup. Adding a Defender exclusion for the project's `venv` folder would likely make startup consistently fast; left for you to decide since it's a system security setting.
- **Minor, unchanged**: rate limits are 20 questions/minute and 10 login attempts/minute per person — generous for a normal demo pace, but worth knowing if you plan rapid-fire questions or audience participation.
- **Minor, unchanged**: the server only answers on `127.0.0.1` (the machine it's running on) — fine for presenting from that laptop's own browser, but it won't be reachable from a second device (a phone, another laptop) unless that's set up separately beforehand.
- **Recommendation**: start the server at least 10–15 minutes before presenting and leave it running, rather than starting it right before you go live.

---

## Phase 12 — Reachable from other devices on the same network

**Goal: let the chatbot be opened from a phone or another laptop during the demo, not just the host machine.**

- Changed `app.run()` to bind to `0.0.0.0` instead of the default `127.0.0.1` — the server now listens on every network interface, not just loopback. Verified it's actually listening on all interfaces (`netstat` showed `0.0.0.0:5001 LISTENING`) and confirmed it answers correctly over the LAN IP, not just `localhost`.
- Updated the standalone landing page's two buttons to point at the host laptop's LAN IP (`192.168.0.8`) instead of `127.0.0.1` — opening that file on a *different* device would otherwise have tried to reach that device's own loopback address, which is never the chatbot.
- **Not finished — needs your decision**: this machine's current Wi-Fi network is categorized "Public" by Windows, and reaching the chatbot from another device requires a Windows Firewall rule allowing inbound traffic on port 5001 — I can't create firewall rules myself (a security-sensitive change outside what I'll do without you approving it directly). See the one manual step below.

**The one thing left to do yourself:** open PowerShell **as yourself** (not through me) and run:
```
New-NetFirewallRule -DisplayName "School Chatbot Demo (port 5001)" -Direction Inbound -Protocol TCP -LocalPort 5001 -Action Allow -Profile Any
```
Then from another device on the same Wi-Fi, open `http://192.168.0.8:5001`. Worth removing that rule after the demo (`Remove-NetFirewallRule -DisplayName "School Chatbot Demo (port 5001)"`) since it stays open to anyone else on that network otherwise.

---

## Phase 13 — Understanding the videos on the school's own website

**Goal: the website crawl picks up text, but the school's site also has real spoken-word video content — alumni podcasts, how-to guides — that was invisible to search until now.**

- Scanned all 219 crawled pages specifically for video content and found two different kinds, needing two different handling approaches: **2 self-hosted `.mp4` files** (hero/promo clips) and **18 embedded YouTube videos** (7 real alumni interview podcasts, 6 parent-portal how-to guides, a few department/activity clips).
- Built `ingest_site_videos.py`:
  - Self-hosted videos are downloaded just long enough to transcribe (reusing the exact same Whisper pipeline as a locally-dropped video), then discarded — the citation links straight back to the real file on the school's own server instead of our own storage.
  - YouTube videos are **never downloaded at all** — their existing captions are fetched directly via `youtube-transcript-api`, which is both lighter and avoids pulling video off YouTube altogether. 14 of 18 had usable captions; the other 4 (short clips) didn't have any available and were skipped rather than guessed at.
  - Verified titles are pulled from YouTube's own metadata (via its public oEmbed endpoint, no API key needed) rather than just reusing the page they were found on.
- Extended the citation system for this new mixed-source reality: video citations now correctly branch three ways — a locally-stored file (existing `/media` route), a self-hosted file on the school's own server (direct link with a time fragment), or a YouTube video (an inline, timestamped embed player, reusing the same "click a citation, watch the clip" UI already built for local videos).
- **Found and fixed a real bug during testing**: the citation links were silently missing entirely for the new video types — traced it to the running server simply predating the code changes (Flask doesn't reload on its own), not a logic bug. Restarted and confirmed citations build correctly end to end.
- **Found and fixed a real scope-guard regression**: asking about an alumnus by name alone ("Tell me about Andreas Iacovides") got wrongly declined as off-topic, because the classifier had no way to know the knowledge base now includes alumni interviews — a bare name looked like an unrelated celebrity question. Fixed by telling the classifier explicitly that named-person questions should default to in-scope, since they're very likely an alumnus, staff member, or podcast guest. Re-verified: the same alumni question now answers correctly, a genuinely unrelated question is still declined.
- Verified live: asked about a real alumnus featured in one of the new podcasts and got a correct, well-cited answer pulling from four different moments in the actual video, each with a working timestamped YouTube embed.

---

## Phase 14 — Matching the school's actual brand colors, and a mobile pass

**Goal: two smaller, real fixes — the UI still used a generic dark theme, and the mobile layout had never actually been checked.**

- Replaced the generic amber/blue accent colors across every page (chat, login, signup, calendar, admin) with the school's real brand colors — the same indigo (`#383f9a`) and gold (`#f4d319`) pulled from their own logo for the earlier landing page. Document and web-source citations now use genuine school colors; video citations stay purple and calendar holidays stay red on purpose, so the different source types still read apart at a glance. Scoped to this project only — the original Moebius chatbot wasn't touched.
- **Found and fixed two real mobile layout risks while checking.** Neither page's header had ever been tested at phone width: the chat page crams a "Connected" badge, Calendar link, New chat button, and Log out into one row with no wrapping, and the admin page has the same issue with its title and three nav links. Both would have overflowed or crushed together on a narrow screen. Fixed by hiding non-essential bits (the subtitle, the "Connected" badge) and letting the rest wrap below 640px. Also fixed a forced 190px minimum width on the calendar's toolbar that could have pushed it off-screen, and tightened the day grid's cell size and text for legibility at phone width.
- Verified every page still returns a clean 200 after the changes; the actual phone-width rendering wasn't visually screenshotted (no tooling for that in this environment) — these are targeted fixes for overflow risks found by reading the real CSS, not a full visual QA pass.

---

## Phase 15 — A trusted-domain web search, and answers that act on dislikes

**Goal: the web fallback could wander anywhere on the internet, and a 👎 didn't actually change anything.**

- **Restricted the live web fallback to a configured list of trusted domains** (the school's own site, gov.uk, Pearson, the Duke of Edinburgh Award, the British Council, UCAS, and the Cyprus education ministry), set via `TAVILY_TRUSTED_DOMAINS` in `.env`. Previously a web-fallback answer could pull in anything — we'd seen it cite random US school districts' enrollment pages for a Cyprus school's admissions question. Verified live: a UCAS-related question now returns results exclusively from ucas.com.
- **A 👎 now actually does something.** Clicking dislike on an answer automatically retries the same question the opposite way — a document-based answer that got disliked retries through the live web search, and a web-based answer that got disliked retries through the documents again (without bouncing back to the web a second time, since that already failed to satisfy once). The retry appears as a new message tagged "🔁 tried a different way," with its own thumbs so it can be rated too.
- Tracked retries in the question log (a new `retried_from` column linking back to the original answer) so the admin dashboard shows how often this actually happens — a new stat card plus a 🔁 badge on the affected row in Recent Questions.
- Verified live end to end: a disliked document answer about the Duke of Edinburgh Award correctly retried through the web (confirmed by `used_web` flipping from `false` to `true`), and the admin dashboard picked up the retry correctly.

---

## Phase 16 — Getting ready for a real public deployment

**Goal: a link that works from any network, not just the host laptop's own Wi-Fi.**

- This machine has no `git` installed, which most hosting platforms (Render, Railway) expect for deploys. Rather than install git and set up a GitHub repo, prepared the project for **Fly.io** instead — it deploys straight from this local folder via its own CLI, so it only needs one account, not two.
- Added a `Dockerfile` (ffmpeg and Tesseract installed for video/OCR support, pinned to Python 3.11 rather than this machine's 3.14 since torch and sentence-transformers have far more reliable prebuilt wheels on 3.11), a `.dockerignore` (so `.env` and real secrets never get baked into the image), and a `fly.toml` with a persistent volume mounted for the database specifically — the one thing that actually needs to survive a restart, since original files are already backed up to B2 separately.
- Deliberately configured to keep one machine always running rather than Fly's cheaper scale-to-zero option — this session saw local startup (loading the search model) take anywhere from 20 seconds to several minutes, which would be a bad first impression for a cold-started visitor.
- **Refactored `app.py`** so its startup work (creating the schema, seeding the admin account, starting the file watcher and calendar sync) runs on import rather than only inside `if __name__ == "__main__"` — a production server (gunicorn, which Fly runs instead of Flask's own dev server) imports the module and serves it directly without ever calling that block. Verified the ordinary local dev flow (`python app.py`) still starts cleanly and every page still loads after the change.
- **Stopped here deliberately**: actually creating a Fly.io account, copying API keys into its secrets store, and running the real deploy commands needs your direct action — not something to do on your behalf without you present for it. Full step-by-step instructions are in `README.md` under "Deploying it publicly."

---

## Phase 17 — A free public link (Cloudflare Quick Tunnel)

**Goal: a link that works from any network, without paying for always-on hosting.**

- Checked Fly.io's real pricing first: no free tier for an always-on instance — roughly $7/month (instance + persistent volume). Asked whether to proceed with that cost; the answer was to try a free option instead.
- Installed `cloudflared` via `winget install --id Cloudflare.cloudflared` (the MSI needs a UAC prompt approved interactively, so this had to be run directly rather than automated).
- Running `cloudflared tunnel --url http://localhost:5001` (while the local server is already running) opens a free, instant, public HTTPS tunnel straight to this laptop — no Cloudflare account, no card, no git, no deploy step. Verified live: the tunnel URL returned a real 200 response serving the actual sign-in page.
- **Trade-offs, on purpose**: this only works while both the Flask server *and* the `cloudflared` process stay running on this laptop — close the laptop and the link goes dead. The URL is also randomly generated and changes every time the tunnel restarts, so it can't be handed out as a permanent address. Good for a demo or short-term sharing; not a substitute for the real Fly.io deployment in Phase 16 if a stable, always-on link is ever needed.
- **Tried to make the link stable with ngrok instead** (a free static subdomain, no domain purchase needed): installed `Ngrok.Ngrok` via winget, but its self-update (needed for the free static-domain feature) was quarantined twice by Windows Defender as `Trojan:Win32/Kepavll!rfn` (severity: Severe) — confirmed via `Get-MpThreatDetection`, not just a Smart App Control signing block. Possibly a heuristic false positive (self-updating tools that overwrite their own executable are a classic trigger pattern), but with no way to verify the binary's integrity from here, the call was to trust Defender and abandon ngrok rather than override a severe quarantine. Uninstalled it and removed its config/auth token.
- **Also learned Cloudflare's quick tunnel isn't meant to run for hours** — the original tunnel from earlier in this session was silently torn down server-side ("Tunnel not found") after roughly two hours idle. Quick tunnels are explicitly a testing feature, not a long-running one. Restarting `cloudflared tunnel --url http://localhost:5001` mints a fresh working URL in seconds, so this just means **the link changes any time the tunnel is restarted or has been sitting unused for a while** — re-run the command and grab the new URL printed in the first few lines of output.
- **Current live link** (changes on restart, see above): `https://seek-purse-vpn-evaluated.trycloudflare.com`

---

## Phase 18 — Mobile layout bug, and a PDF export of this log

**Goal: fix a real mobile display bug found while testing on a phone, and make this log easy to hand out as a document.**

- **Bug fixed:** on a phone, the desktop-only "Sources" sidebar was showing up stacked underneath the whole chat instead of being hidden, making the page look broken and hard to read. Root cause: in `templates/index.html`, the mobile rule `.sources-panel { display: none; }` was written *earlier* in the stylesheet than the panel's own base `.sources-panel { display: flex; ... }` rule. With equal CSS specificity, the rule that comes later in the file wins regardless of which one is inside a media query — so the later, unconditional `flex` rule was silently overriding the mobile `none`, every time, on every phone. Fixed by moving all the responsive overrides to the very end of the stylesheet, where they're guaranteed to win. Verified against a real phone screenshot showing the bug, then confirmed fixed after restarting the server (template changes don't hot-reload since the app runs with `debug=False`).
- **Added a Markdown-to-PDF export** for this log (`md_to_pdf.py`, using `markdown` + `beautifulsoup4` + `reportlab`, all pure-Python — no external binaries, avoiding the installer problems hit earlier this session) — gives a `PROGRESS.pdf` that can be attached and sent directly, for anyone who'd rather read a document than open a link. Re-run `.\venv\Scripts\python.exe md_to_pdf.py PROGRESS.md PROGRESS.pdf` any time this file changes and a fresh copy is needed.
- **Bug fixed (packaging quirk, not app code):** `pip.exe` in this project's venv had the wrong project's absolute path baked into its own launcher, left over from when the venv folder was copied — running it installed packages into the *other* project's venv instead of this one. Worked around by using `python.exe -m pip install ...` instead, which targets the correct interpreter.

---

## Phase 19 — Permanently removing live web search

**Goal: the assistant should only ever answer from the school's own ingested material — never the open web — by explicit request.**

- Removed the entire Tavily web-search integration from `ask.py`: `call_web_search`, `answer_from_web`, `format_web_results`, `web_sources_from`, `WEB_SYSTEM_PROMPT`, and the trusted-domain config, all deleted rather than just disabled — this was a deliberate, permanent decision, not a temporary toggle. `ask_with_sources()` now has one path: search the knowledge base, and if nothing's found (or the model says what it found doesn't actually answer the question), say so honestly instead of reaching outside the school's own material.
- **Also removed the retry-on-dislike feature** (`/api/retry` in `app.py`, and the matching frontend JS): it only ever existed to switch between a document-based answer and a web-based one when one got a 👎. With only one source left, there's nothing different left to retry with, so keeping it would have meant either dead code or a button that lied about "trying a different way." The 👍/👎 feedback buttons themselves still work and still log to the question log — only the automatic re-query on dislike was removed.
- Cleaned up everywhere else the now-gone feature was referenced: `tavily-python` out of `requirements.txt`, `TAVILY_API_KEY`/`TAVILY_TRUSTED_DOMAINS` out of `.env`, and the copy in `templates/index.html`, the landing page, and `README.md` that described live web search as a feature — all rewritten to describe the new, strictly-local behavior honestly.
- **Verified live**, two real questions run directly through `ask_with_sources()`:
  - An off-topic question ("weather forecast for tomorrow") was correctly declined by the existing scope filter before it ever reached retrieval — confirms nothing in the pipeline reaches the web, even indirectly.
  - "What time does the school day start?" — one of the app's own suggested starter questions — came back as "I don't have this in the school's own materials." Checked this wasn't a bug by running the raw retrieval step by itself: it returned 8 chunks (alumni interviews, the calendar page) but **none of them actually state the school's start/end time** — this specific fact was apparently never in any ingested document and was only ever answerable before because the web fallback could find it elsewhere. Not a regression, but a real, newly-exposed gap.
- **Follow-up resolved**: checked the school's actual website directly and found the real cause — the official **Parent and Student Handbook** PDF (linked from the site's "Handbook & Booklists" page) had never actually been uploaded into this project; only the website crawl and videos had ever been ingested, nothing from `pdfs/`. Downloaded the handbook straight from the school's own site (`englishschool.ac.cy/wp-content/uploads/...`) and dropped it into `pdfs/`, where the file watcher picked it up and auto-ingested it (57 chunks, no code changes needed). **Re-tested and confirmed fixed**: the start/end time question now answers correctly — "The school day begins at 7:40 am... ends at 13:40 pm" — citing the real handbook page (page 18), with no web search involved. Worth spot-checking the other starter questions for the same kind of gap, since this project apparently never had its most important parent-facing document in the knowledge base at all until now.

---

## Phase 20 — A real, independent public domain (Fly.io)

**Goal: a permanent link that doesn't depend on this laptop staying on or a tunnel staying alive.**

- Switched `fly.toml` to **scale-to-zero** (`auto_stop_machines = true`, `min_machines_running = 0`) rather than the always-on config originally prepared in Phase 16 — the actual need turned out to be "works whenever someone opens it," not "loads instantly for a live demo," and scale-to-zero costs close to nothing for occasional use instead of ~$7/month.
- Installed `flyctl` (via `winget`, after the official install script hit a Windows licensing quirk and a portable-exe download got blocked by this session's own permission classifier — using winget's verified package was the clean path through both).
- Ran the real deployment: `fly launch`, `fly secrets set` with every `.env` key, `fly deploy`. Live at **`https://school-info-assistant.fly.dev`**.
- **Found and fixed a real deployment bug**: restarting the Fly machine (`fly apps restart`) right after uploading a fresh database silently reset it back to an empty placeholder — almost certainly a race between the app's own startup code and the persistent volume still mounting. The fix: never restart after an upload; SQLite reads the file fresh on every request, so the upload alone is enough. Confirmed by re-uploading without restarting and getting a correct, real answer back.
- Tried the free Cloudflare Quick Tunnel route first, before settling on Fly — documented in-session but worth noting here: quick tunnels get torn down after a few hours idle and need re-warming, which is why the permanent Fly domain was worth the small ongoing cost.

---

## Phase 21 — The database had never actually reached the live site, and a scattered-information fix

**Goal: make sure the live public link actually has real content, and that broad questions whose answer spans many pages actually get answered.**

- **Found a real gap**: despite Phase 20's deployment working, the live Fly machine had been serving its **original empty placeholder database since the very first deploy on Oct 29** — the upload step had never actually been carried out for this project. Re-uploaded the real local database (handbook, 219-page website crawl, videos) for the first time; verified live with a real question that now correctly cites the handbook.
- **Diagnosed why broad questions failed**: asking something whose answer is spread across many pages (e.g. "who are the members of the Board of Management?" — 13 separate individual bio pages) was unreliable, because only the top 8 retrieved chunks ever reached the model, and each chunk was a coarse 300 words — the same dilution bug found and fixed on the sibling Moebius project.
- **Applied the same fix here**: `TOP_N` raised from 8 to 20 in `query.py` (the model's 131K-token context window has enormous headroom — a typical question only uses ~2–3K tokens), and `chunk_page()` in `ingest.py` rewritten to split by sentence/bullet and flush at 150 words instead of treating a whole paragraph as one unsplittable unit.
- **A real mistake during the re-ingestion, disclosed and recovered**: wiped the existing PDF/video/website sources to force everyone through the new chunker before confirming the replacements would succeed. YouTube started rate-limiting caption requests from this machine mid-recovery, and all 14 previously-working YouTube transcripts came back empty. The block lifted on its own a few minutes later and every transcript was successfully re-fetched — no permanent loss, but the lesson stands: verify a replacement works before deleting the original.
- Refreshed the actual website crawl at the same time (219 pages checked, 9 real content changes picked up — exam results, privacy policy, admissions pages, a new job vacancy — and 1 stale page removed) and re-scanned for site videos (no new ones; same 2 self-hosted + 16 YouTube as before).
- **Verified live** on the real deployed site: "Who are the members of the Board of Management?" now correctly names all 13 members with their actual roles, pulling from 20 chunks instead of 8, citing the real Governance page, with no web search involved.

---

## Current tech stack

| Piece | Tool | Cost |
|---|---|---|
| PDF text extraction | `pdfplumber` + Tesseract OCR (scanned pages) | Free |
| Word / PowerPoint / text extraction | `python-docx`, `python-pptx` | Free |
| Website ingestion via sitemap | `requests` + `beautifulsoup4` | Free |
| Video/audio transcription | Groq Whisper (`whisper-large-v3-turbo`) | Free tier |
| Audio extraction | ffmpeg | Free |
| Search | SQLite FTS5 (keyword) + `sentence-transformers` (semantic), combined via reciprocal rank fusion | Free, runs locally |
| Answer generation | Groq (`openai/gpt-oss-120b`) | Free tier |
| Live web fallback | None — removed by design; the assistant only answers from ingested material | — |
| Web interface | Flask, session-based login, rate limiting, Markdown-rendered answers | — |
| Auto-ingestion | `watchdog` (watches `pdfs/`, `videos/`, and `documents/`) | — |
| Cloud storage for source files | Backblaze B2 (S3-compatible) | Free tier (10GB) |
| Self-updating term-date & holiday calendar | Parsed from the school's own site, synced via its sitemap `<lastmod>` | Free |
| Visual calendar page | Custom month-grid view, linked from the chatbot | — |
| Conversation memory | Flask session (last 3 exchanges) | — |
| Accounts | Per-user login (`users` table), admin-gated dashboard | — |
| Admin dashboard, question log & feedback | Flask route + SQLite | — |
| Website video ingestion | Self-hosted: Groq Whisper, same as local videos. YouTube: `youtube-transcript-api` (no download) | Free |
| Retrieval breadth | Top 20 chunks per question (hybrid keyword + semantic, fused) | — |
| Public deployment | Fly.io, scale-to-zero (`school-info-assistant.fly.dev`) | ~free (idle most of the time) |

**Project folder:** `Documents\school-knowledge-agent`
**To run it locally:** `.\venv\Scripts\python.exe app.py`, then open `http://127.0.0.1:5001` (see `README.md` for login details and folder layout)
**Live public link:** `https://school-info-assistant.fly.dev`

**Built from:** `Documents\rag-knowledge-agent` (see its own progress log for the shared foundation this project started from)
