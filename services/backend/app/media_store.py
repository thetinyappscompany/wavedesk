"""S3 media — presign + download. Raw S3 keys never leave the server; the
messages API exposes only has_media, and media_url returns a short-lived
presigned URL. Graceful when boto3/creds absent."""

import os
from functools import lru_cache

try:
    import boto3
    from botocore.client import Config
except ImportError:  # pragma: no cover
    boto3 = None
    Config = None


def media_bucket() -> str:
    return os.environ.get("S3_MEDIA_BUCKET") or "wavedesk-media"


def _make_client(endpoint: str | None):
    if boto3 is None or not os.environ.get("S3_ACCESS_KEY"):
        return None
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ.get("S3_ACCESS_KEY"),
        aws_secret_access_key=os.environ.get("S3_SECRET_KEY"),
        region_name=os.environ.get("S3_REGION") or "us-east-1",
        config=Config(signature_version="s3v4") if Config else None,
    )


@lru_cache
def _client():
    """Internal client — server-side get/put over the private network."""
    return _make_client(os.environ.get("S3_ENDPOINT"))


@lru_cache
def _presign_client():
    """Client used ONLY to mint browser-facing presigned GET URLs. SigV4 bakes
    the host into the signature, so the URL must be signed against the PUBLIC
    endpoint (e.g. https://media.<domain> proxied to MinIO) — a URL signed
    against the internal service endpoint (http://srv-captain--minio:9000) is
    unreachable from a user's browser AND blocked as mixed content on an https
    page. Falls back to S3_ENDPOINT for dev where they're the same."""
    return _make_client(
        os.environ.get("S3_PUBLIC_ENDPOINT") or os.environ.get("S3_ENDPOINT")
    )


def presigned_url(key: str, expires: int = 300) -> str | None:
    client = _presign_client()
    if client is None:
        return None
    return client.generate_presigned_url(
        "get_object", Params={"Bucket": media_bucket(), "Key": key}, ExpiresIn=expires
    )


def download_bytes(key: str) -> bytes | None:
    client = _client()
    if client is None:
        return None
    obj = client.get_object(Bucket=media_bucket(), Key=key)
    return obj["Body"].read()
