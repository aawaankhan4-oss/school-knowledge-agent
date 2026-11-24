"""Keeps a structured table of the school's term dates and public holidays
in sync with the school's own website.

Chunk-based search is a poor fit for a page that's mostly a long list of
dates — the exact "Cyprus Independence Day" line can get lost among dozens
of similar-looking chunks. Instead, this parses the calendar page's actual
HTML structure into clean (event, date range) rows stored in their own
table, and re-syncs automatically whenever the page's own sitemap <lastmod>
shows it's actually changed — not on a blind timer.
"""
import os
import re
import threading
import time
from datetime import datetime
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from ingest import get_connection

load_dotenv()

CALENDAR_URL = os.environ.get(
    "CALENDAR_URL", "https://englishschool.ac.cy/news-events/school-calendar/"
)
CALENDAR_SITEMAP_URL = os.environ.get(
    "CALENDAR_SITEMAP_URL", "https://englishschool.ac.cy/page-sitemap.xml"
)
SYNC_INTERVAL_SECONDS = 6 * 60 * 60  # re-check for changes every 6 hours while the app runs

SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; school-knowledge-agent/1.0)"}
REQUEST_TIMEOUT = 15


def _get_remote_lastmod():
    """Look up the calendar page's own <lastmod> from its sitemap entry."""
    resp = requests.get(CALENDAR_SITEMAP_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    for url_el in root.findall(f"{SITEMAP_NS}url"):
        loc = url_el.findtext(f"{SITEMAP_NS}loc")
        if loc and loc.strip() == CALENDAR_URL:
            lastmod = url_el.findtext(f"{SITEMAP_NS}lastmod")
            return lastmod.strip() if lastmod else None
    return None


def _parse_date(text):
    """'Thursday, 1 October 2026' -> a date object."""
    cleaned = re.sub(r"^\w+,\s*", "", re.sub(r"\s+", " ", text.strip()))
    return datetime.strptime(cleaned, "%d %B %Y").date()


def _parse_calendar_html(html):
    """The calendar page is an accordion: a section-header <h3> per term
    ("Autumn Term", "Public and School Holidays", ...), each followed by
    event <h3>s shaped like `<h3>Event Name<span class="font-light">Date
    [– end date]</span>[<span class="bg-secondary">note</span>]</h3>`."""
    soup = BeautifulSoup(html, "html.parser")
    container = soup.find("section", class_="calendar-section") or soup

    events = []
    category = None
    for h3 in container.find_all("h3"):
        date_span = h3.find("span", class_="font-light")
        if date_span:
            name_node = h3.find(string=True, recursive=False)
            name = re.sub(r"\s+", " ", name_node).strip() if name_node else ""
            if not name:
                continue

            date_text = re.sub(r"\s+", " ", date_span.get_text(" ", strip=True)).strip()
            parts = re.split(r"\s*[–-]\s*", date_text, maxsplit=1)
            try:
                start = _parse_date(parts[0])
                end = _parse_date(parts[1]) if len(parts) > 1 else start
            except ValueError:
                continue  # not something that parses as a clean date — skip it

            note_span = h3.find("span", class_=lambda c: c and "bg-secondary" in c)
            note = note_span.get_text(strip=True) if note_span else None

            events.append(
                {
                    "category": category,
                    "event_name": name,
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "note": note,
                }
            )
        else:
            plain_span = h3.find("span")
            if plain_span and not plain_span.get("class"):
                category = plain_span.get_text(strip=True)

    return events


def sync_calendar(conn, force=False):
    """Re-fetch and re-parse the calendar page only if its sitemap lastmod
    has changed since the last sync (or this is the first run ever)."""
    try:
        remote_lastmod = _get_remote_lastmod()
    except Exception as e:
        print(f"[calendar] Couldn't check the calendar page's sitemap entry: {e}")
        return False

    row = conn.execute("SELECT lastmod FROM calendar_sync_state WHERE id = 1").fetchone()
    stored_lastmod = row[0] if row else None

    if not force and remote_lastmod and remote_lastmod == stored_lastmod:
        return False  # unchanged since the last sync — nothing to do

    try:
        resp = requests.get(CALENDAR_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        events = _parse_calendar_html(resp.text)
    except Exception as e:
        print(f"[calendar] Couldn't fetch/parse the calendar page: {e}")
        return False

    if not events:
        print("[calendar] Parsed zero events from the calendar page — leaving existing data in place.")
        return False

    now = datetime.now().isoformat()
    conn.execute("DELETE FROM calendar_events")
    for ev in events:
        conn.execute(
            "INSERT INTO calendar_events (category, event_name, start_date, end_date, note, source_url) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ev["category"], ev["event_name"], ev["start_date"], ev["end_date"], ev["note"], CALENDAR_URL),
        )
    conn.execute("DELETE FROM calendar_sync_state")
    conn.execute(
        "INSERT INTO calendar_sync_state (id, source_url, lastmod, synced_at) VALUES (1, ?, ?, ?)",
        (CALENDAR_URL, remote_lastmod, now),
    )
    conn.commit()
    print(f"[calendar] Synced {len(events)} calendar events from {CALENDAR_URL}.")
    return True


def get_calendar_events(conn):
    """Raw (category, event_name, start_date, end_date, note) rows, ordered
    by start date — used by the calendar page as well as the prompt."""
    return conn.execute(
        "SELECT category, event_name, start_date, end_date, note "
        "FROM calendar_events ORDER BY start_date"
    ).fetchall()


def format_calendar_for_prompt(conn):
    """A clean, compact listing of every known term date and holiday, ready
    to hand straight to the model — or None if nothing has been synced yet."""
    rows = conn.execute(
        "SELECT category, event_name, start_date, end_date, note "
        "FROM calendar_events ORDER BY start_date"
    ).fetchall()
    if not rows:
        return None
    lines = []
    for category, name, start, end, note in rows:
        date_str = start if start == end else f"{start} to {end}"
        note_str = f" ({note})" if note else ""
        prefix = f"[{category}] " if category else ""
        lines.append(f"- {prefix}{name}: {date_str}{note_str}")
    return "\n".join(lines)


def _sync_loop():
    while True:
        try:
            conn = get_connection()
            sync_calendar(conn)
            conn.close()
        except Exception as e:
            print(f"[calendar] Background sync error: {e}")
        time.sleep(SYNC_INTERVAL_SECONDS)


def start_calendar_sync():
    """Sync once immediately (covers a fresh database or a first run), then
    keep re-checking in the background for as long as the app runs — so the
    calendar stays current without anyone having to remember to re-run
    anything by hand.

    The first sync runs in the same background thread as every later one,
    not before it — a slow or unreachable school website at startup used to
    block the Flask server from binding its port at all. Now the app always
    starts immediately and just answers from whatever calendar data it
    already has until the first sync catches up."""
    threading.Thread(target=_sync_loop, daemon=True).start()
