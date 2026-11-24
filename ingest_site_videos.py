"""Finds videos embedded on the school's own website — both self-hosted
.mp4 files and embedded YouTube videos — and ingests them into the
knowledge base the same way a dropped-in video file is: transcribed,
chunked by time, and searchable with clickable timestamp citations.

Unlike videos/, there's no local file to watch here either, so — like
ingest_web.py — this is a script you run by hand (or trigger from the
admin page) rather than something that fires automatically.

Self-hosted videos are downloaded just long enough to transcribe, then
discarded — the citation links straight back to the real file on the
school's own server. YouTube videos are never downloaded at all: their
existing captions (auto-generated or manual) are fetched directly, which
is both lighter and more respectful of YouTube's terms than pulling down
the video itself.

Run with: .\\venv\\Scripts\\python.exe ingest_site_videos.py
"""
import re
import tempfile
from pathlib import Path

import requests
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound, VideoUnavailable

from ingest import already_ingested, get_connection, init_db, insert_chunk, insert_source
from ingest_video import chunk_segments, extract_audio, transcribe as transcribe_file
from ingest_web import HEADERS, REQUEST_TIMEOUT, SITEMAP_URL, list_page_urls

MP4_RE = re.compile(r'https?://[^"\'\s>]+\.mp4')
YOUTUBE_RE = re.compile(r'(?:youtube\.com/embed/|youtu\.be/)([a-zA-Z0-9_-]{6,})')

_yt_api = YouTubeTranscriptApi()


def find_site_videos():
    """Crawl every page in the sitemap and collect every self-hosted .mp4
    URL and YouTube video id found embedded in it. Returns
    (mp4_urls: set[str], youtube_ids: dict[str, str]) — youtube_ids maps
    video id to the page it was first found on, used as a fallback title
    source."""
    pages = list_page_urls(SITEMAP_URL)
    mp4_urls = set()
    youtube_ids = {}

    for url, _lastmod in pages:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            text = resp.text
        except Exception as e:
            print(f"Couldn't check '{url}' for videos: {e}")
            continue
        mp4_urls.update(MP4_RE.findall(text))
        for video_id in YOUTUBE_RE.findall(text):
            youtube_ids.setdefault(video_id, url)

    return mp4_urls, youtube_ids


def _youtube_title(video_id, fallback):
    """The real video title via YouTube's public oEmbed endpoint — no API
    key needed. Falls back to the page it was found on if that fails."""
    try:
        resp = requests.get(
            "https://www.youtube.com/oembed",
            params={"url": f"https://youtu.be/{video_id}", "format": "json"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()["title"]
    except Exception:
        return fallback


def ingest_youtube_video(conn, video_id, source_page_url):
    origin_url = f"https://youtu.be/{video_id}"
    if already_ingested(conn, origin_url):
        print(f"Skipping '{origin_url}' — already in the database.")
        return

    try:
        fetched = _yt_api.fetch(video_id)
    except (TranscriptsDisabled, NoTranscriptFound):
        print(f"Skipped '{origin_url}': no captions available for this video.")
        return
    except VideoUnavailable:
        print(f"Skipped '{origin_url}': video is unavailable (private, deleted, or region-locked).")
        return
    except Exception as e:
        print(f"Skipped '{origin_url}': couldn't fetch captions ({e}).")
        return

    segments = [
        (s.start, s.start + s.duration, s.text.strip())
        for s in fetched
        if s.text.strip() and s.text.strip() != "[Music]"
    ]
    if not segments:
        print(f"No speech found in captions for '{origin_url}'.")
        return

    title = _youtube_title(video_id, f"Video from {source_page_url}")
    source_id = insert_source(conn, title, origin_url, "youtube")

    chunk_index = 0
    for start, end, text in chunk_segments(segments):
        insert_chunk(conn, source_id, chunk_index, text, start_time=start, end_time=end)
        chunk_index += 1

    conn.commit()
    print(f"Ingested '{title}': {chunk_index} chunks from {origin_url}")


def ingest_self_hosted_video(conn, video_url, source_page_url):
    if already_ingested(conn, video_url):
        print(f"Skipping '{video_url}' — already in the database.")
        return

    print(f"Downloading '{video_url}' for transcription...")
    try:
        resp = requests.get(video_url, headers=HEADERS, timeout=60)
        resp.raise_for_status()
    except Exception as e:
        print(f"Skipped '{video_url}': couldn't download it ({e}).")
        return

    suffix = Path(video_url).suffix or ".mp4"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.write(resp.content)
    tmp.close()
    tmp_path = Path(tmp.name)

    try:
        segments = transcribe_file(tmp_path)
    except Exception as e:
        print(f"Skipped '{video_url}': couldn't transcribe it ({e}).")
        return
    finally:
        tmp_path.unlink(missing_ok=True)

    if not segments:
        print(f"No speech detected in '{video_url}'.")
        return

    title = Path(video_url).stem.replace("_", " ").replace("-", " ")
    source_id = insert_source(conn, title, video_url, "video")

    chunk_index = 0
    for start, end, text in chunk_segments(segments):
        insert_chunk(conn, source_id, chunk_index, text, start_time=start, end_time=end)
        chunk_index += 1

    conn.commit()
    print(f"Ingested '{title}': {chunk_index} chunks from {video_url}")


def run_full_video_crawl():
    conn = get_connection()
    init_db(conn)

    print("Scanning the website for videos...")
    mp4_urls, youtube_ids = find_site_videos()
    print(f"Found {len(mp4_urls)} self-hosted video(s) and {len(youtube_ids)} YouTube video(s).")

    for video_url in sorted(mp4_urls):
        ingest_self_hosted_video(conn, video_url, "")

    for video_id, page_url in youtube_ids.items():
        ingest_youtube_video(conn, video_id, page_url)

    conn.close()
    summary = {"self_hosted": len(mp4_urls), "youtube": len(youtube_ids)}
    print(f"Done: {summary}")
    return summary


if __name__ == "__main__":
    run_full_video_crawl()
