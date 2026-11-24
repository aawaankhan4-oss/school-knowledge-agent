# Deployment image for Fly.io (or any Docker host). Pinned to Python 3.11
# rather than matching the local dev venv's version — torch and
# sentence-transformers have far more reliably available prebuilt wheels on
# 3.11 for Linux, avoiding a slow/fragile from-source build in the image.
FROM python:3.11-slim

# ffmpeg: audio extraction for video transcription.
# tesseract-ocr: OCR fallback for scanned PDF pages.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# The persistent Fly volume mounts here — everything else (pdfs/, videos/,
# documents/, web_snapshots/) is fine to lose on a restart, since anything
# that matters either gets uploaded to Backblaze B2 or lives in the
# database itself, which is the one thing that needs to survive.
RUN mkdir -p /app/db

EXPOSE 8080

# --workers 1: the app keeps background state in each process (the file
# watcher thread, the calendar sync loop, and Flask-Limiter's in-memory rate
# counters) — more than one worker would duplicate all of that rather than
# share it. --timeout 120: transcription calls to Groq can take a while on a
# longer video and shouldn't be killed mid-request.
CMD ["gunicorn", "--workers", "1", "--timeout", "120", "--bind", "0.0.0.0:8080", "app:app"]
