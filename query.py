"""Step 5 — search the knowledge base for chunks relevant to a question.

Uses hybrid search: keyword matching (FTS5, good at exact wording) combined
with semantic matching (embeddings, good at paraphrased questions), merged
with reciprocal rank fusion so a chunk that scores well on either counts.
"""
import re
import sqlite3
from pathlib import Path

from embeddings import cosine_similarity, deserialize_embedding, embed_text

ROOT = Path(__file__).parent
DB_PATH = ROOT / "db" / "knowledge.db"

TOP_N = 20  # the model's context window (131K tokens) has far more room than
# this ever approaches — a typical question only uses ~2-3K tokens — so a
# small TOP_N was the real bottleneck for any question whose answer is
# spread across several pages rather than sitting in one chunk
RRF_K = 60  # standard reciprocal-rank-fusion constant


def get_connection():
    return sqlite3.connect(DB_PATH)


def build_fts_query(question):
    """Turn a free-form question into a safe FTS5 query.

    FTS5 treats punctuation as syntax (quotes, minus signs, etc.), so a raw
    question like "What's the price?" can crash the search. Pulling out just
    the words and OR-ing them together sidesteps that and casts a wide net.
    """
    words = re.findall(r"\w+", question)
    return " OR ".join(words) if words else question


def keyword_search(conn, question, top_n=TOP_N):
    """Exact-wording search via SQLite's full-text index."""
    fts_query = build_fts_query(question)
    return conn.execute(
        """
        SELECT chunks.id, chunks.text, chunks.page_number, chunks.start_time,
               sources.title, sources.origin_path, sources.type
        FROM chunks_fts
        JOIN chunks ON chunks.id = chunks_fts.rowid
        JOIN sources ON sources.id = chunks.source_id
        WHERE chunks_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (fts_query, top_n),
    ).fetchall()


def semantic_search(conn, question, top_n=TOP_N):
    """Meaning-based search: compare the question's embedding against every
    chunk's embedding and return the closest matches. Catches paraphrased
    questions that share no exact words with the source text."""
    rows = conn.execute(
        """
        SELECT chunks.id, chunks.text, chunks.page_number, chunks.start_time,
               sources.title, sources.origin_path, sources.type, chunk_embeddings.embedding
        FROM chunk_embeddings
        JOIN chunks ON chunks.id = chunk_embeddings.chunk_id
        JOIN sources ON sources.id = chunks.source_id
        """
    ).fetchall()
    if not rows:
        return []

    query_vec = embed_text(question)
    scored = [
        (
            cosine_similarity(query_vec, deserialize_embedding(blob)),
            cid, text, page, start_time, title, origin_path, source_type,
        )
        for cid, text, page, start_time, title, origin_path, source_type, blob in rows
    ]
    scored.sort(key=lambda r: r[0], reverse=True)
    return [
        (cid, text, page, start_time, title, origin_path, source_type)
        for _, cid, text, page, start_time, title, origin_path, source_type in scored[:top_n]
    ]


def hybrid_search(conn, question, top_n=TOP_N):
    """Merge keyword and semantic results with reciprocal rank fusion: a
    chunk's score is the sum of 1/(k + rank) from each list it appears in,
    so chunks that rank well on either search count, and chunks that rank
    well on both rise to the top."""
    keyword_results = keyword_search(conn, question, top_n=top_n)
    semantic_results = semantic_search(conn, question, top_n=top_n)

    scores = {}
    info = {}
    for results in (keyword_results, semantic_results):
        for rank, (cid, text, page, start_time, title, origin_path, source_type) in enumerate(results):
            scores[cid] = scores.get(cid, 0) + 1 / (RRF_K + rank)
            info[cid] = (text, page, start_time, title, origin_path, source_type)

    ranked_ids = sorted(scores, key=scores.get, reverse=True)[:top_n]
    return [info[cid] for cid in ranked_ids]


def search(conn, question, top_n=TOP_N):
    return hybrid_search(conn, question, top_n=top_n)


def main():
    question = input("Ask a question: ")
    conn = get_connection()
    results = search(conn, question)
    conn.close()

    if not results:
        print("No matching chunks found.")
        return

    for text, page, start_time, title, origin_path, source_type in results:
        if source_type == "web":
            location = origin_path
        elif page is not None:
            label = {"pptx": "slide", "docx": "part", "text": "part"}.get(source_type, "page")
            location = f"{label} {page}"
        else:
            minutes, seconds = divmod(int(start_time or 0), 60)
            location = f"{minutes}:{seconds:02d}"
        print(f"\n[{title} | {location} | {source_type}]")
        print(text[:300])


if __name__ == "__main__":
    main()
