"""Local web interface for the school knowledge chatbot. Run with:
    .\\venv\\Scripts\\python.exe app.py
then open http://127.0.0.1:5001 in a browser.

Runs on a different port (5001) than the original rag-knowledge-agent (5000)
so both can run at the same time without conflicting.
"""
import json
import os
import threading
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, abort, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

import analytics
import auth
import calendar_sync
import cloud_storage
import ingest_web
from ask import AnswerError, ask_with_sources
from ingest import get_connection, init_db
from ingest_video import VIDEO_DIR
from watcher import start_watching

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]

limiter = Limiter(get_remote_address, app=app, storage_uri="memory://")

# Conversation history lives in the session cookie, so it's kept short and
# each stored answer is trimmed — plenty for follow-up context without
# risking the cookie's ~4KB size limit.
MAX_HISTORY_TURNS = 3
MAX_STORED_ANSWER_CHARS = 400


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        if not session.get("is_admin"):
            abort(403)
        return view(*args, **kwargs)

    return wrapped


@app.errorhandler(429)
def handle_rate_limit(e):
    return jsonify({"error": "Too many requests — please slow down and try again shortly."}), 429


@app.route("/signup", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def signup():
    error = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password", "")
        if len(password) < 6:
            error = "Password must be at least 6 characters."
        else:
            conn = get_connection()
            try:
                user_id = auth.create_user(conn, username, password)
                session.clear()
                session["user_id"] = user_id
                session["username"] = username
                session["is_admin"] = False
                session.permanent = True
                conn.close()
                return redirect(url_for("index"))
            except auth.UsernameTaken as e:
                error = str(e)
            except ValueError as e:
                error = str(e)
            conn.close()
    return render_template("signup.html", error=error)


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    error = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password", "")
        conn = get_connection()
        user = auth.verify_login(conn, username, password)
        conn.close()
        if user:
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["is_admin"] = user["is_admin"]
            session.permanent = True
            return redirect(url_for("index"))
        error = "Incorrect username or password."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    return render_template("index.html")


@app.route("/calendar")
@login_required
def calendar_page():
    conn = get_connection()
    rows = calendar_sync.get_calendar_events(conn)
    conn.close()
    events = [
        {"category": category, "name": name, "start": start, "end": end, "note": note}
        for category, name, start, end, note in rows
    ]
    return render_template("calendar.html", events_json=json.dumps(events))


@app.route("/media/<path:filename>")
@login_required
def media(filename):
    # If this file was uploaded to cloud storage (and its local copy
    # deleted to save disk space), redirect to a short-lived signed URL
    # instead of trying to serve it from disk.
    if cloud_storage.is_configured():
        conn = get_connection()
        row = conn.execute(
            "SELECT cloud_key FROM sources WHERE origin_path = ?",
            (str(VIDEO_DIR / filename),),
        ).fetchone()
        conn.close()
        if row and row[0]:
            return redirect(cloud_storage.get_presigned_url(row[0]))

    # send_from_directory rejects any attempt to escape VIDEO_DIR (e.g. "../"),
    # so a filename can't be used to read arbitrary files off the server.
    try:
        return send_from_directory(VIDEO_DIR, filename)
    except FileNotFoundError:
        abort(404)


def _answer_and_log(question):
    """Shared helper for /api/ask: run the pipeline, update the session's
    conversation history, and log the question for analytics.
    Returns (result_dict, status_code) — status_code is only set on error."""
    history = session.get("history", [])

    try:
        result = ask_with_sources(question, history=history)
    except AnswerError as e:
        return {"error": str(e)}, e.status_code
    except Exception:
        app.logger.exception("Unexpected error while answering a question")
        return {"error": "Something went wrong on our end. Please try again."}, 500

    if not result.get("blocked"):
        history.append(
            {"question": question, "answer": result["answer"][:MAX_STORED_ANSWER_CHARS]}
        )
        session["history"] = history[-MAX_HISTORY_TURNS:]

    try:
        conn = get_connection()
        log_id = analytics.log_question(
            conn,
            session.get("user_id"),
            question,
            used_web=result["used_web"],
            blocked=result.get("blocked", False),
            block_reason=result.get("block_reason"),
        )
        conn.close()
        result["log_id"] = log_id
    except Exception:
        app.logger.exception("Couldn't log this question for analytics")

    return result, None


@app.route("/api/ask", methods=["POST"])
@login_required
@limiter.limit("20 per minute")
def api_ask():
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"error": "Question is required."}), 400

    result, error_status = _answer_and_log(question)
    return jsonify(result), (error_status or 200)


@app.route("/api/feedback", methods=["POST"])
@login_required
def api_feedback():
    data = request.get_json(silent=True) or {}
    log_id = data.get("log_id")
    feedback = data.get("feedback")
    if not log_id or feedback not in ("up", "down"):
        return jsonify({"error": "log_id and a valid feedback value are required."}), 400

    conn = get_connection()
    analytics.record_feedback(conn, log_id, feedback)
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/reset", methods=["POST"])
@login_required
def api_reset():
    session.pop("history", None)
    return jsonify({"ok": True})


@app.route("/admin")
@admin_required
def admin():
    conn = get_connection()
    source_counts = dict(
        conn.execute("SELECT type, COUNT(*) FROM sources GROUP BY type").fetchall()
    )
    total_chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    calendar_row = conn.execute(
        "SELECT source_url, lastmod, synced_at FROM calendar_sync_state WHERE id = 1"
    ).fetchone()
    calendar_event_count = conn.execute("SELECT COUNT(*) FROM calendar_events").fetchone()[0]
    question_stats = analytics.stats(conn)
    recent = analytics.recent_questions(conn)
    blocked = analytics.blocked_questions(conn)
    per_user = analytics.per_user_stats(conn)
    keywords = analytics.top_keywords(conn)
    conn.close()

    return render_template(
        "admin.html",
        source_counts=source_counts,
        total_chunks=total_chunks,
        calendar_row=calendar_row,
        calendar_event_count=calendar_event_count,
        question_stats=question_stats,
        recent=recent,
        blocked=blocked,
        per_user=per_user,
        keywords=keywords,
    )


@app.route("/admin/recrawl", methods=["POST"])
@admin_required
def admin_recrawl():
    threading.Thread(target=ingest_web.run_full_crawl, daemon=True).start()
    return jsonify({"ok": True, "message": "Re-crawl started in the background — check back in a few minutes."})


@app.route("/admin/sync-calendar", methods=["POST"])
@admin_required
def admin_sync_calendar():
    conn = get_connection()
    changed = calendar_sync.sync_calendar(conn, force=True)
    conn.close()
    message = "Calendar re-synced." if changed else "Calendar checked — nothing changed."
    return jsonify({"ok": True, "message": message})


# Runs on import, not just under `if __name__ == "__main__"` — a production
# server (gunicorn) imports this module and serves the `app` object directly
# without ever calling app.run(), so startup work has to happen here to run
# either way. Make sure the database schema exists even on a totally fresh
# install (no PDFs/videos/documents ingested yet) — otherwise the first
# question asked before anything is ingested crashes with "no such table".
_startup_conn = get_connection()
init_db(_startup_conn)
auth.seed_admin_from_env(_startup_conn)
_startup_conn.close()
start_watching()
calendar_sync.start_calendar_sync()

if __name__ == "__main__":
    # Local development only — in production, gunicorn serves `app` directly
    # (see Dockerfile) instead of using Flask's own dev server.
    # host="0.0.0.0" makes this reachable from other devices on the same
    # network (phones, other laptops) at this machine's local IP — not just
    # from the browser on this machine via 127.0.0.1.
    app.run(debug=False, host="0.0.0.0", port=5001)
