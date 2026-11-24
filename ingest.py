"""Ingest PDFs from pdfs/ into the SQLite knowledge base (see schema.sql).

Run this once per new document, offline (not during a chat conversation).
"""
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber
import pytesseract

import cloud_storage
from embeddings import embed_text, serialize_embedding

ROOT = Path(__file__).parent
PDF_DIR = ROOT / "pdfs"
DB_PATH = ROOT / "db" / "knowledge.db"
SCHEMA_PATH = ROOT / "schema.sql"

CHUNK_TARGET_WORDS = 150  # smaller chunks retrieve more precisely for narrow
# factual questions — found via a real "who owns this company" failure on
# the sibling Moebius project, where a team member's name and title sat in
# a ~300-word chunk, diluted by a few hundred words of unrelated detail,
# and never ranked highly enough to surface. 300 was the original target.

# pytesseract needs to know where the Tesseract program lives; it isn't on PATH here.
_TESSERACT_EXE = Path.home() / "AppData/Local/Programs/Tesseract-OCR/tesseract.exe"
if _TESSERACT_EXE.exists():
    pytesseract.pytesseract.tesseract_cmd = str(_TESSERACT_EXE)


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn):
    conn.executescript(SCHEMA_PATH.read_text())
    conn.commit()
    _migrate(conn)


def _migrate(conn):
    """CREATE TABLE IF NOT EXISTS in schema.sql only takes effect for a
    brand-new database — it's a no-op on a table that already exists, so
    columns added later need an explicit ALTER TABLE here for existing
    databases to pick them up."""
    existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(sources)")}
    if "cloud_key" not in existing_columns:
        conn.execute("ALTER TABLE sources ADD COLUMN cloud_key TEXT")
        conn.commit()
    if "source_lastmod" not in existing_columns:
        conn.execute("ALTER TABLE sources ADD COLUMN source_lastmod TEXT")
        conn.commit()

    log_columns = {row[1] for row in conn.execute("PRAGMA table_info(question_log)")}
    for column, definition in (
        ("user_id", "INTEGER"),
        ("blocked", "INTEGER DEFAULT 0"),
        ("block_reason", "TEXT"),
        ("feedback", "TEXT"),
        ("retried_from", "INTEGER"),
    ):
        if column not in log_columns:
            conn.execute(f"ALTER TABLE question_log ADD COLUMN {column} {definition}")
            conn.commit()


def ocr_page(page):
    """Render a page as an image and run OCR on it, for scanned/image-only pages."""
    image = page.to_image(resolution=200).original
    return pytesseract.image_to_string(image)


def extract_pages(pdf_path):
    """Yield (page_number, text) for each page, 1-indexed.

    Falls back to OCR when normal text extraction finds nothing, which
    happens for scanned pages (the page is really just a picture).
    """
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if not text.strip():
                text = ocr_page(page)
            yield i, text


def chunk_page(text, target_words=CHUNK_TARGET_WORDS):
    """Merge paragraphs on a page into chunks of roughly target_words.

    Accumulates by sentence (and, for a block with no sentence punctuation,
    by "•" bullet) rather than treating a whole paragraph as one atomic,
    unsplittable unit, and flushes a chunk the moment the running word
    count reaches the target. That matters for a PDF table (a bio, a spec
    sheet, a timetable) that extracts as one unbroken block with no
    internal blank lines: without this, a short, specific fact near the
    start of a long table block stays buried among a few hundred words of
    unrelated content for the rest of that block, diluting both the
    keyword and semantic search signal for it enough that a narrow
    question whose answer is exactly that one fact can fail to retrieve it
    at all.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks = []
    current_words = []

    def flush():
        if current_words:
            chunks.append(" ".join(current_words))
            current_words.clear()

    for para in paragraphs:
        words = para.split()
        if len(words) <= target_words:
            current_words.extend(words)
            if len(current_words) >= target_words:
                flush()
            continue

        flush()
        for unit in re.split(r"(?<=[.!?])\s+|\s+(?=[•])", para):
            unit_words = unit.split()
            if not unit_words:
                continue
            if len(unit_words) > target_words:
                flush()
                for i in range(0, len(unit_words), target_words):
                    chunks.append(" ".join(unit_words[i : i + target_words]))
                continue
            current_words.extend(unit_words)
            if len(current_words) >= target_words:
                flush()
    flush()
    return chunks


def insert_source(conn, title, path, source_type="pdf", source_lastmod=None):
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO sources (title, type, origin_path, added_at, source_lastmod) VALUES (?, ?, ?, ?, ?)",
        (title, source_type, str(path), now, source_lastmod),
    )
    return cur.lastrowid


def delete_source(conn, source_id):
    """Remove a source and everything derived from it: its chunks, their
    FTS entries and embeddings, and (if it was backed up) its cloud copy.
    Used when a web page has been removed from the site, or is about to be
    re-ingested after changing."""
    row = conn.execute("SELECT cloud_key FROM sources WHERE id = ?", (source_id,)).fetchone()
    cloud_key = row[0] if row else None

    chunk_ids = [r[0] for r in conn.execute("SELECT id FROM chunks WHERE source_id = ?", (source_id,))]
    if chunk_ids:
        placeholders = ",".join("?" * len(chunk_ids))
        conn.execute(f"DELETE FROM chunks_fts WHERE rowid IN ({placeholders})", chunk_ids)
        conn.execute(f"DELETE FROM chunk_embeddings WHERE chunk_id IN ({placeholders})", chunk_ids)
        conn.execute(f"DELETE FROM chunks WHERE id IN ({placeholders})", chunk_ids)
    conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    conn.commit()

    if cloud_key:
        import cloud_storage

        try:
            cloud_storage.delete_object(cloud_key)
        except Exception as e:
            print(f"Warning: couldn't delete cloud object {cloud_key}: {e}")


def insert_chunk(conn, source_id, chunk_index, text, page_number=None, start_time=None, end_time=None):
    cur = conn.execute(
        """
        INSERT INTO chunks (source_id, chunk_index, text, page_number, start_time, end_time)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (source_id, chunk_index, text, page_number, start_time, end_time),
    )
    chunk_id = cur.lastrowid
    conn.execute("INSERT INTO chunks_fts (rowid, text) VALUES (?, ?)", (chunk_id, text))
    embedding = serialize_embedding(embed_text(text))
    conn.execute(
        "INSERT INTO chunk_embeddings (chunk_id, embedding) VALUES (?, ?)", (chunk_id, embedding)
    )
    return chunk_id


def backfill_embeddings(conn):
    """Embed any chunk that doesn't have one yet — covers chunks inserted
    before semantic search was added."""
    rows = conn.execute(
        "SELECT id, text FROM chunks WHERE id NOT IN (SELECT chunk_id FROM chunk_embeddings)"
    ).fetchall()
    if not rows:
        return
    for chunk_id, text in rows:
        embedding = serialize_embedding(embed_text(text))
        conn.execute(
            "INSERT INTO chunk_embeddings (chunk_id, embedding) VALUES (?, ?)", (chunk_id, embedding)
        )
    conn.commit()
    print(f"Backfilled embeddings for {len(rows)} existing chunk(s).")


def upload_and_cleanup(conn, source_id, path):
    """If cloud storage is configured, back up the original file and delete
    the local copy to save disk space. Safe to call even when cloud storage
    isn't set up — it just does nothing in that case. Only deletes the
    local file after the upload has actually succeeded, so a failed upload
    never loses data."""
    if not cloud_storage.is_configured():
        return

    key = f"{source_id}_{path.name}"
    try:
        cloud_storage.upload_file(path, key)
    except Exception as e:
        print(f"Warning: cloud upload failed for '{path.name}' — keeping the local copy. ({e})")
        return

    conn.execute("UPDATE sources SET cloud_key = ? WHERE id = ?", (key, source_id))
    conn.commit()
    path.unlink(missing_ok=True)
    print(f"Uploaded '{path.name}' to cloud storage and removed the local copy.")


def already_ingested(conn, pdf_path):
    row = conn.execute(
        "SELECT id FROM sources WHERE origin_path = ?", (str(pdf_path),)
    ).fetchone()
    return row is not None


def ingest_pdf(conn, pdf_path):
    if already_ingested(conn, pdf_path):
        print(f"Skipping '{pdf_path.name}' — already in the database.")
        return

    title = pdf_path.stem
    source_id = insert_source(conn, title, pdf_path)

    chunk_index = 0
    prev_sentence = ""  # carried into the next chunk so context isn't lost at a boundary
    for page_number, text in extract_pages(pdf_path):
        if not text.strip():
            continue
        for chunk_text in chunk_page(text):
            full_text = f"{prev_sentence} {chunk_text}".strip() if prev_sentence else chunk_text
            insert_chunk(conn, source_id, chunk_index, full_text, page_number)
            chunk_index += 1
            sentences = chunk_text.split(". ")
            prev_sentence = sentences[-1] if sentences else ""

    conn.commit()
    print(f"Ingested '{title}': {chunk_index} chunks from {pdf_path.name}")
    upload_and_cleanup(conn, source_id, pdf_path)


def main():
    conn = get_connection()
    init_db(conn)
    backfill_embeddings(conn)

    pdf_files = sorted(PDF_DIR.glob("*.pdf"))
    if not pdf_files:
        print(f"Database ready at {DB_PATH}. No PDFs found in {PDF_DIR} yet — drop some in and re-run.")
        conn.close()
        return

    for pdf_path in pdf_files:
        ingest_pdf(conn, pdf_path)

    conn.close()


if __name__ == "__main__":
    main()
