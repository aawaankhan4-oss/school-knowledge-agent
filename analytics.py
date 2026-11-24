"""A lightweight log of what people actually ask (and who), for the admin
page — including questions the scope guard declined and why, plus simple
thumbs up/down feedback on answered ones. Only question text is stored,
never answer content.
"""
import re
from collections import Counter
from datetime import datetime

STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "do", "does", "did", "i",
    "you", "it", "to", "of", "for", "in", "on", "at", "and", "or", "what",
    "when", "where", "how", "who", "which", "can", "will", "be", "this",
    "that", "my", "me", "about", "with", "your", "there", "any", "have",
    "has", "does", "if", "we", "us", "our",
}


def log_question(conn, user_id, question, used_web=False, blocked=False, block_reason=None, retried_from=None):
    cur = conn.execute(
        "INSERT INTO question_log (question, used_web, asked_at, user_id, blocked, block_reason, retried_from) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            question, 1 if used_web else 0, datetime.now().isoformat(), user_id,
            1 if blocked else 0, block_reason, retried_from,
        ),
    )
    conn.commit()
    return cur.lastrowid


def record_feedback(conn, log_id, feedback):
    if feedback not in ("up", "down"):
        raise ValueError("feedback must be 'up' or 'down'")
    conn.execute("UPDATE question_log SET feedback = ? WHERE id = ?", (feedback, log_id))
    conn.commit()


def recent_questions(conn, limit=25):
    """(question, used_web, asked_at, blocked, block_reason, feedback, username, retried_from)"""
    return conn.execute(
        """
        SELECT question_log.question, question_log.used_web, question_log.asked_at,
               question_log.blocked, question_log.block_reason, question_log.feedback,
               COALESCE(users.username, 'unknown'), question_log.retried_from
        FROM question_log
        LEFT JOIN users ON users.id = question_log.user_id
        ORDER BY question_log.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def blocked_questions(conn, limit=25):
    """(question, block_reason, asked_at, username)"""
    return conn.execute(
        """
        SELECT question_log.question, question_log.block_reason, question_log.asked_at,
               COALESCE(users.username, 'unknown')
        FROM question_log
        LEFT JOIN users ON users.id = question_log.user_id
        WHERE question_log.blocked = 1
        ORDER BY question_log.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def per_user_stats(conn):
    """(username, total, blocked_count, web_count, thumbs_up, thumbs_down, last_asked)"""
    return conn.execute(
        """
        SELECT COALESCE(users.username, 'unknown') AS username,
               COUNT(*) AS total,
               SUM(CASE WHEN question_log.blocked = 1 THEN 1 ELSE 0 END) AS blocked_count,
               SUM(CASE WHEN question_log.used_web = 1 THEN 1 ELSE 0 END) AS web_count,
               SUM(CASE WHEN question_log.feedback = 'up' THEN 1 ELSE 0 END) AS thumbs_up,
               SUM(CASE WHEN question_log.feedback = 'down' THEN 1 ELSE 0 END) AS thumbs_down,
               MAX(question_log.asked_at) AS last_asked
        FROM question_log
        LEFT JOIN users ON users.id = question_log.user_id
        GROUP BY username
        ORDER BY total DESC
        """
    ).fetchall()


def stats(conn):
    total = conn.execute("SELECT COUNT(*) FROM question_log WHERE blocked = 0").fetchone()[0]
    web_fallback = conn.execute(
        "SELECT COUNT(*) FROM question_log WHERE used_web = 1 AND blocked = 0"
    ).fetchone()[0]
    blocked = conn.execute("SELECT COUNT(*) FROM question_log WHERE blocked = 1").fetchone()[0]
    thumbs_up = conn.execute("SELECT COUNT(*) FROM question_log WHERE feedback = 'up'").fetchone()[0]
    thumbs_down = conn.execute("SELECT COUNT(*) FROM question_log WHERE feedback = 'down'").fetchone()[0]
    retries = conn.execute("SELECT COUNT(*) FROM question_log WHERE retried_from IS NOT NULL").fetchone()[0]
    return {
        "total_questions": total,
        "web_fallback_count": web_fallback,
        "blocked_count": blocked,
        "thumbs_up": thumbs_up,
        "thumbs_down": thumbs_down,
        "retries": retries,
    }


def top_keywords(conn, limit=12):
    """The most common meaningful words across answered questions — a quick
    read on what topics people are actually asking about."""
    rows = conn.execute("SELECT question FROM question_log WHERE blocked = 0").fetchall()
    counts = Counter()
    for (question,) in rows:
        for word in re.findall(r"[a-zA-Z']+", question.lower()):
            if len(word) > 2 and word not in STOPWORDS:
                counts[word] += 1
    return counts.most_common(limit)
