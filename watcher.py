"""Watches pdfs/, videos/, and documents/, automatically ingesting anything
dropped in so you don't have to run the ingest scripts by hand. Started
automatically by app.py.
"""
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from ingest import PDF_DIR, get_connection, ingest_pdf, init_db
from ingest_docs import SUPPORTED_EXTENSIONS as DOC_EXTENSIONS
from ingest_docs import DOCS_DIR, ingest_document
from ingest_video import SUPPORTED_EXTENSIONS as VIDEO_EXTENSIONS
from ingest_video import VIDEO_DIR, ingest_video


class NewFileHandler(FileSystemEventHandler):
    def on_created(self, event):
        self._maybe_ingest(event)

    def on_moved(self, event):
        # covers browsers/apps that download to a temp name, then rename to the real extension
        self._maybe_ingest(event, path_attr="dest_path")

    def _maybe_ingest(self, event, path_attr="src_path"):
        if event.is_directory:
            return
        path = Path(getattr(event, path_attr))
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            threading.Thread(target=self._wait_and_ingest_pdf, args=(path,), daemon=True).start()
        elif suffix in VIDEO_EXTENSIONS:
            threading.Thread(target=self._wait_and_ingest_video, args=(path,), daemon=True).start()
        elif suffix in DOC_EXTENSIONS:
            threading.Thread(target=self._wait_and_ingest_doc, args=(path,), daemon=True).start()

    def _wait_and_ingest_pdf(self, path):
        if not self._wait_until_stable(path):
            return
        print(f"[watcher] New PDF detected: {path.name} — ingesting...")
        try:
            conn = get_connection()
            init_db(conn)
            ingest_pdf(conn, path)
            conn.close()
        except Exception as e:
            print(f"[watcher] Failed to ingest {path.name}: {e}")

    def _wait_and_ingest_video(self, path):
        if not self._wait_until_stable(path):
            return
        print(f"[watcher] New video/audio detected: {path.name} — transcribing...")
        try:
            conn = get_connection()
            init_db(conn)
            ingest_video(conn, path)
            conn.close()
        except Exception as e:
            print(f"[watcher] Failed to ingest {path.name}: {e}")

    def _wait_and_ingest_doc(self, path):
        if not self._wait_until_stable(path):
            return
        print(f"[watcher] New document detected: {path.name} — ingesting...")
        try:
            conn = get_connection()
            init_db(conn)
            ingest_document(conn, path)
            conn.close()
        except Exception as e:
            print(f"[watcher] Failed to ingest {path.name}: {e}")

    @staticmethod
    def _wait_until_stable(path, checks=20, interval=0.5):
        """Wait until the file's size stops changing, so we don't read a
        half-written file while it's still being copied or downloaded."""
        last_size = -1
        for _ in range(checks):
            if not path.exists():
                return False
            size = path.stat().st_size
            if size == last_size and size > 0:
                return True
            last_size = size
            time.sleep(interval)
        return path.exists()


def start_watching():
    PDF_DIR.mkdir(exist_ok=True)
    VIDEO_DIR.mkdir(exist_ok=True)
    DOCS_DIR.mkdir(exist_ok=True)
    handler = NewFileHandler()
    observer = Observer()
    observer.schedule(handler, str(PDF_DIR), recursive=False)
    observer.schedule(handler, str(VIDEO_DIR), recursive=False)
    observer.schedule(handler, str(DOCS_DIR), recursive=False)
    observer.daemon = True
    observer.start()
    print(f"[watcher] Watching {PDF_DIR}, {VIDEO_DIR}, and {DOCS_DIR} for new files...")
    return observer
