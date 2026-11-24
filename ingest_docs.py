"""Ingest Word documents, PowerPoint slides, and plain text/Markdown notes
from documents/ into the SQLite knowledge base.

Each file type contributes chunks shaped just like PDFs and videos, just
with a different idea of "location":
  - PowerPoint: real slide numbers (reuses the page_number column)
  - Word / plain text: no page boundaries are stored in these formats the
    way a PDF stores them, so chunks are labelled by position instead
    ("part 1", "part 2", ...) rather than a fabricated page number

Run this once per new file, offline (not during a chat conversation).
"""
from pathlib import Path

import docx
from pptx import Presentation

from ingest import (
    already_ingested,
    chunk_page,
    get_connection,
    init_db,
    insert_chunk,
    insert_source,
    upload_and_cleanup,
)

ROOT = Path(__file__).parent
DOCS_DIR = ROOT / "documents"

SUPPORTED_EXTENSIONS = {".docx", ".pptx", ".txt", ".md"}


def extract_docx(path):
    """Return the full text of a Word document — paragraphs and table cells — as one string."""
    document = docx.Document(path)
    parts = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n\n".join(parts)


def extract_pptx_slides(path):
    """Yield (slide_number, text) for each slide, 1-indexed."""
    presentation = Presentation(path)
    for i, slide in enumerate(presentation.slides, start=1):
        texts = [
            shape.text_frame.text
            for shape in slide.shapes
            if shape.has_text_frame and shape.text_frame.text.strip()
        ]
        yield i, "\n".join(texts)


def ingest_pptx(conn, path):
    title = path.stem
    source_id = insert_source(conn, title, path, "pptx")

    chunk_index = 0
    for slide_number, text in extract_pptx_slides(path):
        if not text.strip():
            continue
        for chunk_text in chunk_page(text):
            insert_chunk(conn, source_id, chunk_index, chunk_text, page_number=slide_number)
            chunk_index += 1

    conn.commit()
    print(f"Ingested '{title}': {chunk_index} chunks from {path.name}")
    upload_and_cleanup(conn, source_id, path)


def ingest_flat_text(conn, path, source_type):
    """Shared path for Word docs and plain text/Markdown notes — both are
    just one long piece of text with no real page boundaries, so chunks are
    labelled by position ("part N") instead of a page number."""
    title = path.stem
    text = extract_docx(path) if source_type == "docx" else path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        print(f"No text found in '{path.name}'.")
        return

    source_id = insert_source(conn, title, path, source_type)

    chunk_index = 0
    prev_sentence = ""  # carried into the next chunk so context isn't lost at a boundary
    for chunk_text in chunk_page(text):
        full_text = f"{prev_sentence} {chunk_text}".strip() if prev_sentence else chunk_text
        insert_chunk(conn, source_id, chunk_index, full_text, page_number=chunk_index + 1)
        chunk_index += 1
        sentences = chunk_text.split(". ")
        prev_sentence = sentences[-1] if sentences else ""

    conn.commit()
    print(f"Ingested '{title}': {chunk_index} chunks from {path.name}")
    upload_and_cleanup(conn, source_id, path)


def ingest_document(conn, path):
    if already_ingested(conn, path):
        print(f"Skipping '{path.name}' — already in the database.")
        return

    suffix = path.suffix.lower()
    try:
        if suffix == ".pptx":
            ingest_pptx(conn, path)
        elif suffix == ".docx":
            ingest_flat_text(conn, path, "docx")
        elif suffix in (".txt", ".md"):
            ingest_flat_text(conn, path, "text")
    except Exception as e:
        print(f"Skipped '{path.name}': couldn't read this file ({e}).")


def main():
    conn = get_connection()
    init_db(conn)

    DOCS_DIR.mkdir(exist_ok=True)
    files = sorted(p for p in DOCS_DIR.iterdir() if p.suffix.lower() in SUPPORTED_EXTENSIONS)
    if not files:
        print(f"No documents found in {DOCS_DIR} yet — drop some in and re-run.")
        conn.close()
        return

    for path in files:
        ingest_document(conn, path)

    conn.close()


if __name__ == "__main__":
    main()
