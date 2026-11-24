"""Optional cloud storage for the original PDF/video/document files, so a
large knowledge base doesn't fill up local disk. Uses Backblaze B2's
S3-compatible API (works with any S3-compatible provider via the same env
vars, e.g. Cloudflare R2, if you switch providers later).

Entirely optional: if the four B2_* environment variables aren't set, every
function here is a no-op and the app behaves exactly as it did before —
files just stay local. This is what keeps the feature backward compatible
with a knowledge base that was never configured for cloud storage.
"""
import os

import boto3
from botocore.config import Config
from dotenv import load_dotenv

load_dotenv()

_KEY_ID = os.environ.get("B2_KEY_ID")
_APPLICATION_KEY = os.environ.get("B2_APPLICATION_KEY")
_BUCKET_NAME = os.environ.get("B2_BUCKET_NAME")
_ENDPOINT = os.environ.get("B2_ENDPOINT")  # e.g. "s3.us-west-004.backblazeb2.com"


def is_configured():
    return bool(_KEY_ID and _APPLICATION_KEY and _BUCKET_NAME and _ENDPOINT)


_client = None


def _get_client():
    global _client
    if _client is None:
        # B2 only accepts Signature Version 4 — boto3's default (SigV2-style
        # presigned URLs) gets a 401 from B2, so this must be forced explicitly.
        # The region is embedded in the endpoint hostname (e.g. "eu-central-003"
        # from "s3.eu-central-003.backblazeb2.com") and SigV4 needs one supplied.
        region = _ENDPOINT.split(".")[1] if _ENDPOINT else None
        _client = boto3.client(
            "s3",
            endpoint_url=f"https://{_ENDPOINT}",
            aws_access_key_id=_KEY_ID,
            aws_secret_access_key=_APPLICATION_KEY,
            region_name=region,
            config=Config(signature_version="s3v4"),
        )
    return _client


def upload_file(local_path, key):
    """Upload a local file to the bucket under `key`. Raises on failure —
    callers should catch this and keep the local file rather than deleting
    something that never made it to the cloud."""
    _get_client().upload_file(str(local_path), _BUCKET_NAME, key)


def get_presigned_url(key, expires_in=600):
    """A temporary (default 10-minute) URL that grants access to one file
    without making the bucket itself public."""
    return _get_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": _BUCKET_NAME, "Key": key},
        ExpiresIn=expires_in,
    )


def delete_object(key):
    _get_client().delete_object(Bucket=_BUCKET_NAME, Key=key)
