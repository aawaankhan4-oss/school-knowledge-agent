"""Ingest videos/audio from videos/ into the SQLite knowledge base.

Every file is first passed through ffmpeg to pull out just the audio track
(mono, low bitrate) before transcription. That does two things: it shrinks
even a large video down to a small file before it's uploaded, and it means
any format ffmpeg understands works here — not just the handful of formats
Groq's Whisper endpoint accepts directly. The small extracted audio copy
used for transcription is always temporary and gets deleted right after.
The original video file itself is kept locally in videos/ (needed for
click-to-play citations) unless cloud storage is configured — see
cloud_storage.py — in which case it's uploaded and the local copy removed.

Uses Groq's hosted Whisper model to transcribe speech into timestamped text,
then groups the transcript into ~75-second chunks — the audio equivalent of
how ingest.py groups PDF pages into ~300-word chunks.

Run this once per new video, offline (not during a chat conversation).
"""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import groq
from dotenv import load_dotenv
from groq import Groq

from ingest import already_ingested, get_connection, init_db, insert_chunk, insert_source, upload_and_cleanup

load_dotenv()

ROOT = Path(__file__).parent
VIDEO_DIR = ROOT / "videos"

TRANSCRIBE_MODEL = "whisper-large-v3-turbo"  # fast, free tier
CHUNK_TARGET_SECONDS = 75  # aim for 60-90 seconds of speech per chunk, per the plan

# Any of these are accepted — ffmpeg extracts the audio track before
# transcription, so common video containers work even though Groq's
# Whisper endpoint doesn't take them directly.
SUPPORTED_EXTENSIONS = {
    ".mp4", ".mov", ".mkv", ".avi", ".wmv", ".flv", ".webm",
    ".mp3", ".wav", ".m4a", ".ogg", ".flac", ".mpeg", ".mpga",
}

_groq = Groq(api_key=os.environ["GROQ_API_KEY"])


def _find_ffmpeg():
    """Locate the ffmpeg executable. Checks PATH first (works once a new
    terminal has picked up winget's PATH change), then falls back to
    searching winget's install folder directly, since that path includes a
    version-specific hash that shouldn't be hardcoded."""
    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path

    winget_packages = Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
    matches = sorted(winget_packages.glob("Gyan.FFmpeg*/**/bin/ffmpeg.exe"))
    if matches:
        return str(matches[0])

    raise FileNotFoundError(
        "ffmpeg isn't installed. Install it with: "
        "winget install --id Gyan.FFmpeg -e --source winget"
    )


_FFMPEG = _find_ffmpeg()


def extract_audio(video_path):
    """Pull a small mono audio track out of a video/audio file for
    transcription. Returns the path to a temporary mp3 the caller must
    delete when done."""
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp.close()
    tmp_path = Path(tmp.name)

    result = subprocess.run(
        [
            _FFMPEG, "-y", "-i", str(video_path),
            "-vn",  # drop any video stream, audio only
            "-ac", "1",  # mono
            "-ar", "16000",  # 16kHz, plenty for speech
            "-b:a", "32k",  # low bitrate — keeps file size small
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg couldn't process this file: {result.stderr.strip()[-300:]}")
    return tmp_path


def transcribe(video_path):
    """Return a list of (start, end, text) segments for a video/audio file."""
    audio_path = extract_audio(video_path)
    try:
        response = _groq.audio.transcriptions.create(
            model=TRANSCRIBE_MODEL,
            file=audio_path,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )
    finally:
        audio_path.unlink(missing_ok=True)
    segments = getattr(response, "segments", None) or []
    return [(s["start"], s["end"], s["text"].strip()) for s in segments if s["text"].strip()]


def chunk_segments(segments, target_seconds=CHUNK_TARGET_SECONDS):
    """Group consecutive transcript segments into ~target_seconds chunks.

    Carries the last sentence of one chunk into the next (same trick as the
    PDF chunker) so an answer isn't cut off mid-thought at a chunk boundary.
    The chunk's timestamp always points at its own new content, not the
    carried-over sentence, so "jump to this moment" links stay accurate.
    """
    chunks = []
    current_texts = []
    chunk_start = None
    prev_sentence = ""

    def flush(end_time):
        nonlocal prev_sentence
        full_text = " ".join(current_texts)
        display_text = f"{prev_sentence} {full_text}".strip() if prev_sentence else full_text
        chunks.append((chunk_start, end_time, display_text))
        sentences = full_text.split(". ")
        prev_sentence = sentences[-1] if sentences else ""

    for start, end, text in segments:
        if chunk_start is None:
            chunk_start = start
        current_texts.append(text)
        if end - chunk_start >= target_seconds:
            flush(end)
            current_texts = []
            chunk_start = None
    if current_texts:
        flush(segments[-1][1])
    return chunks


def ingest_video(conn, video_path):
    if already_ingested(conn, video_path):
        print(f"Skipping '{video_path.name}' — already in the database.")
        return

    print(f"Transcribing '{video_path.name}'... (this can take a moment)")
    try:
        segments = transcribe(video_path)
    except RuntimeError as e:
        print(f"Skipped '{video_path.name}': {e}")
        return
    except groq.RateLimitError:
        print(f"Skipped '{video_path.name}': transcription is rate-limited right now — try again shortly.")
        return
    except groq.AuthenticationError:
        print(f"Skipped '{video_path.name}': the Groq API key looks invalid. Check GROQ_API_KEY in .env.")
        return
    except (groq.APIConnectionError, groq.APITimeoutError):
        print(f"Skipped '{video_path.name}': couldn't reach the transcription service — check your internet connection.")
        return
    except groq.APIStatusError as e:
        print(
            f"Skipped '{video_path.name}': transcription service returned an error "
            f"(status {e.status_code}). The file may be too large or an unsupported format."
        )
        return

    if not segments:
        print(f"No speech detected in '{video_path.name}'.")
        return

    title = video_path.stem
    source_id = insert_source(conn, title, video_path, "video")

    chunk_index = 0
    for start, end, text in chunk_segments(segments):
        insert_chunk(conn, source_id, chunk_index, text, start_time=start, end_time=end)
        chunk_index += 1

    conn.commit()
    print(f"Ingested '{title}': {chunk_index} chunks from {video_path.name}")
    upload_and_cleanup(conn, source_id, video_path)


def main():
    conn = get_connection()
    init_db(conn)

    VIDEO_DIR.mkdir(exist_ok=True)
    video_files = sorted(p for p in VIDEO_DIR.iterdir() if p.suffix.lower() in SUPPORTED_EXTENSIONS)
    if not video_files:
        print(f"No videos found in {VIDEO_DIR} yet — drop some in and re-run.")
        conn.close()
        return

    for video_path in video_files:
        ingest_video(conn, video_path)

    conn.close()


if __name__ == "__main__":
    main()
