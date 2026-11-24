"""Crawl a WordPress-style XML sitemap and ingest each page's visible text
into the knowledge base, the same way PDFs/videos/documents are.

Unlike the other source types there's no local file for the watcher to
notice — pages live on the school's own website — so this is a script you
run by hand rather than something that fires automatically (or trigger it
from the admin page — see app.py's /admin/recrawl). A page already in the
database is only re-ingested if the sitemap's <lastmod> for it has actually
changed since last time; a page that's disappeared from the sitemap
entirely gets removed from the knowledge base too.

Run with: .\\venv\\Scripts\\python.exe ingest_web.py
"""
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup, Comment
from dotenv import load_dotenv

import cloud_storage
from ingest import (
    chunk_page,
    delete_source,
    get_connection,
    init_db,
    insert_chunk,
    insert_source,
    upload_and_cleanup,
)

load_dotenv()

ROOT = Path(__file__).parent
SNAPSHOT_DIR = ROOT / "web_snapshots"

SITEMAP_URL = os.environ.get("SITEMAP_URL")

# Sub-sitemaps to leave out: category/author sitemaps are just archive
# listings with no real content of their own, and post-sitemap is the
# news/blog feed — large (600+ articles) and mostly time-sensitive. Remove
# a pattern from this list (in .env-adjacent code here) to include that
# content too.
EXCLUDE_SITEMAP_PATTERNS = ("category-sitemap", "author-sitemap", "post-sitemap")

SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; school-knowledge-agent/1.0)"}
REQUEST_TIMEOUT = 15
POLITE_DELAY_SECONDS = 0.3  # small pause between page fetches so the crawl doesn't hammer the site


def fetch_xml(url):
    resp = _get_with_retries(url)
    return ET.fromstring(resp.content)


def list_page_urls(sitemap_url):
    """Resolve a sitemap (index-of-sitemaps or a plain page list) down to a
    flat list of (url, lastmod) pairs, recursing into sub-sitemaps as
    needed. lastmod is None for a <url> entry that doesn't carry one."""
    root = fetch_xml(sitemap_url)

    if root.tag == f"{SITEMAP_NS}sitemapindex":
        pages = []
        for sitemap_el in root.findall(f"{SITEMAP_NS}sitemap"):
            sub_url = sitemap_el.findtext(f"{SITEMAP_NS}loc")
            if not sub_url:
                continue
            sub_url = sub_url.strip()
            if any(pattern in sub_url for pattern in EXCLUDE_SITEMAP_PATTERNS):
                print(f"Skipping sub-sitemap '{sub_url}' (excluded).")
                continue
            pages.extend(list_page_urls(sub_url))
        return pages

    pages = []
    for url_el in root.findall(f"{SITEMAP_NS}url"):
        loc = url_el.findtext(f"{SITEMAP_NS}loc")
        if not loc:
            continue
        lastmod = url_el.findtext(f"{SITEMAP_NS}lastmod")
        pages.append((loc.strip(), lastmod.strip() if lastmod else None))
    return pages


# Matches nav/menu/sidebar/footer/breadcrumb/cookie wrapper elements. Many
# WordPress themes (this one included) build their navigation out of plain
# <ul id="menu-primary"> lists rather than a semantic <nav> tag, so tag-name
# stripping alone misses it entirely — this catches it by id/class instead.
NOISE_ATTR_PATTERN = re.compile(r"(?:^|[\s_-])(menu|nav|breadcrumb|sidebar|footer|cookie)(?:$|[\s_-])|q-links", re.I)


def _is_noise(tag):
    if tag.attrs is None:  # already decomposed as part of an earlier noise element
        return False
    attrs = " ".join((tag.get("class") or []) + [tag.get("id") or ""])
    return bool(NOISE_ATTR_PATTERN.search(attrs))


def _get_with_retries(url, attempts=3, backoff_seconds=1.5):
    """A crawl this long (300+ requests to one server) will hit the odd
    transient timeout or connection blip — worth a couple of retries
    before giving up on an otherwise perfectly good page."""
    last_error = None
    for attempt in range(attempts):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp
        except requests.exceptions.RequestException as e:
            last_error = e
            if attempt < attempts - 1:
                time.sleep(backoff_seconds)
    raise last_error


def extract_page_text(url):
    """Fetch a page and pull out its visible text: a title, plus the
    paragraph/heading/list/table text with navigation and script noise
    stripped out."""
    resp = _get_with_retries(url)
    soup = BeautifulSoup(resp.text, "html.parser")

    title_tag = soup.find("h1") or soup.title
    title = title_tag.get_text(strip=True) if title_tag else url

    for tag in soup(["script", "style", "nav", "header", "footer", "noscript", "svg", "form", "iframe"]):
        tag.decompose()
    # WordPress nav-menu links are usually classed on the <li> itself
    # ("menu-item ..."), not on the wrapping <ul>, so <li> has to be checked too.
    for tag in soup.find_all(["ul", "ol", "div", "section", "li"]):
        if _is_noise(tag):
            tag.decompose()

    main = soup.find("main") or soup.find("article") or soup.body or soup
    blocks = [
        el.get_text(" ", strip=True)
        for el in main.find_all(["p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "td", "blockquote"])
    ]

    # Some pages on this site hydrate their real content client-side and
    # leave it sitting in an HTML comment as a fallback/placeholder — a
    # plain HTTP fetch never runs that JavaScript, so without this the
    # actual answer text (e.g. FAQ answers) would be invisible entirely.
    for comment in main.find_all(string=lambda s: isinstance(s, Comment)):
        if "<" not in comment:
            continue
        commented_soup = BeautifulSoup(str(comment), "html.parser")
        blocks.extend(
            el.get_text(" ", strip=True)
            for el in commented_soup.find_all(["p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "td", "blockquote"])
        )

    text = "\n\n".join(b for b in blocks if b)
    return title, text


def _slugify(url):
    path = urlparse(url).path.strip("/")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", path).strip("-")
    return slug or "index"


def archive_snapshot(conn, source_id, url, text):
    """Save a text snapshot of the page to cloud storage (if configured), so
    the knowledge base keeps a record even if the live page later changes or
    disappears. There's no local file to start from the way there is for a
    PDF or video, so one is written just long enough to reuse the same
    upload-then-delete path everything else uses."""
    if not cloud_storage.is_configured():
        return
    SNAPSHOT_DIR.mkdir(exist_ok=True)
    snapshot_path = SNAPSHOT_DIR / f"{_slugify(url)}.txt"
    snapshot_path.write_text(text, encoding="utf-8")
    upload_and_cleanup(conn, source_id, snapshot_path)


def _existing_web_source(conn, url):
    """(id, source_lastmod) for a URL already in the database, or None."""
    return conn.execute(
        "SELECT id, source_lastmod FROM sources WHERE origin_path = ? AND type = 'web'", (url,)
    ).fetchone()


def ingest_web_page(conn, url, remote_lastmod=None):
    existing = _existing_web_source(conn, url)
    if existing:
        existing_id, stored_lastmod = existing
        if remote_lastmod and remote_lastmod == stored_lastmod:
            print(f"Skipping '{url}' — unchanged since last sync.")
            return
        print(f"Re-ingesting '{url}' — changed since last sync.")
        delete_source(conn, existing_id)

    try:
        title, text = extract_page_text(url)
    except Exception as e:
        print(f"Skipped '{url}': couldn't fetch/parse this page ({e}).")
        return

    if not text.strip():
        print(f"No text found on '{url}'.")
        return

    source_id = insert_source(conn, title, url, "web", source_lastmod=remote_lastmod)

    # Prepend the title so short, answer-only chunks (FAQ pages especially,
    # where the answer text itself rarely repeats the question's own
    # wording) are still findable by keyword and semantic search.
    indexed_text = f"{title}\n\n{text}"

    chunk_index = 0
    prev_sentence = ""  # carried into the next chunk so context isn't lost at a boundary
    for chunk_text in chunk_page(indexed_text):
        full_text = f"{prev_sentence} {chunk_text}".strip() if prev_sentence else chunk_text
        insert_chunk(conn, source_id, chunk_index, full_text, page_number=chunk_index + 1)
        chunk_index += 1
        sentences = chunk_text.split(". ")
        prev_sentence = sentences[-1] if sentences else ""

    conn.commit()
    print(f"Ingested '{title}': {chunk_index} chunks from {url}")
    archive_snapshot(conn, source_id, url, text)


def prune_removed_pages(conn, current_urls):
    """Remove any 'web' source whose URL is no longer in the sitemap at
    all — the page was taken down or moved, not just edited."""
    existing = conn.execute("SELECT id, origin_path FROM sources WHERE type = 'web'").fetchall()
    removed = 0
    for source_id, origin_path in existing:
        if origin_path not in current_urls:
            print(f"Removing '{origin_path}' — no longer in the sitemap.")
            delete_source(conn, source_id)
            removed += 1
    return removed


LOCK_PATH = ROOT / ".crawl.lock"


def run_full_crawl():
    """Crawl the whole sitemap: ingest new pages, re-ingest changed ones,
    and prune pages that have disappeared. Returns a small summary dict —
    used by both the command-line entry point and the admin page's
    "re-crawl now" button.

    Guarded by a lock file so two crawls (e.g. the admin button clicked
    twice, or a manual run overlapping the app's own) can't run against the
    same database at once — interleaved DELETE/INSERT cycles from two
    crawlers corrupt each other's lastmod bookkeeping, which is exactly
    what caused a real false-positive prune during testing.
    """
    if not SITEMAP_URL:
        return {"error": "SITEMAP_URL is not set in .env"}

    try:
        lock_fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return {"error": "A crawl is already in progress — try again shortly."}

    try:
        conn = get_connection()
        init_db(conn)

        print(f"Reading sitemap: {SITEMAP_URL}")
        pages = list_page_urls(SITEMAP_URL)
        print(f"Found {len(pages)} page(s) to check.")

        for url, lastmod in pages:
            ingest_web_page(conn, url, remote_lastmod=lastmod)
            time.sleep(POLITE_DELAY_SECONDS)

        # Before permanently deleting anything, re-fetch the sitemap a
        # second, independent time — a page missing from a single fetch
        # could just be a transient hiccup on the school's server, not a
        # real removal. Only prune a page that's missing from *both*.
        try:
            confirm_pages = list_page_urls(SITEMAP_URL)
            current_urls = {url for url, _ in pages} | {url for url, _ in confirm_pages}
            removed = prune_removed_pages(conn, current_urls)
        except Exception as e:
            print(f"Couldn't re-confirm the sitemap before pruning — skipping pruning this run. ({e})")
            removed = 0

        conn.close()
    finally:
        os.close(lock_fd)
        LOCK_PATH.unlink(missing_ok=True)

    summary = {"checked": len(pages), "removed": removed}
    print(f"Crawl complete: {summary}")
    return summary


if __name__ == "__main__":
    run_full_crawl()
