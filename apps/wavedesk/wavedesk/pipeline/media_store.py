# Copyright (c) 2026, WaveDesk
# License: proprietary
"""Object-store access for WhatsApp media (P4.5 / media pipeline).

The wa-gateway downloads inbound media from WhatsApp's CDN and parks the bytes in
S3/MinIO under a workspace-scoped key. Frappe never talks to WhatsApp; it serves
that media to the SPA via short-lived presigned URLs (the bucket stays private)
and, for voice notes, hands the audio to transcription (P4.5 Whisper).

Config mirrors the gateway's env so both point at the same bucket. Secrets from
env only (root non-negotiable #8). Degrades gracefully: if boto3 or the config is
absent, callers get None instead of an exception, so the inbox still renders a
media placeholder.
"""

import os

import frappe

DEFAULT_URL_TTL = 600  # seconds — long enough to load, short enough to stay private


def _conf(key: str, default: str | None = None) -> str | None:
    """Env first (non-negotiable #8), site_config fallback for dev benches."""
    return os.environ.get(key) or frappe.conf.get(key.lower()) or default


def media_bucket() -> str:
    return _conf("S3_MEDIA_BUCKET", "wavedesk-media") or "wavedesk-media"


def _client():
    """A boto3 S3 client, or None when boto3/credentials are unavailable."""
    access = _conf("S3_ACCESS_KEY")
    secret = _conf("S3_SECRET_KEY")
    if not access or not secret:
        return None
    try:
        import boto3  # bundled with Frappe (S3 backups); optional at runtime
    except ImportError:
        return None
    return boto3.client(
        "s3",
        endpoint_url=_conf("S3_ENDPOINT", "http://localhost:9000"),
        region_name=_conf("S3_REGION", "us-east-1"),
        aws_access_key_id=access,
        aws_secret_access_key=secret,
    )


def presigned_url(key: str, ttl: int = DEFAULT_URL_TTL) -> str | None:
    """Short-lived GET URL for a media object, or None if unconfigured."""
    if not key:
        return None
    client = _client()
    if client is None:
        return None
    try:
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": media_bucket(), "Key": key},
            ExpiresIn=ttl,
        )
    except Exception:
        frappe.logger("wavedesk.media").warning({"event": "presign_failed"})
        return None


def download_bytes(key: str) -> bytes | None:
    """Fetch a media object's raw bytes (used by P4.5 transcription), or None."""
    if not key:
        return None
    client = _client()
    if client is None:
        return None
    try:
        obj = client.get_object(Bucket=media_bucket(), Key=key)
        return obj["Body"].read()
    except Exception:
        frappe.logger("wavedesk.media").warning({"event": "download_failed"})
        return None
