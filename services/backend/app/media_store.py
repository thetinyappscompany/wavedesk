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


@lru_cache
def _client():
    if boto3 is None or not os.environ.get("S3_ACCESS_KEY"):
        return None
    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("S3_ENDPOINT"),
        aws_access_key_id=os.environ.get("S3_ACCESS_KEY"),
        aws_secret_access_key=os.environ.get("S3_SECRET_KEY"),
        region_name=os.environ.get("S3_REGION") or "us-east-1",
        config=Config(signature_version="s3v4") if Config else None,
    )


def presigned_url(key: str, expires: int = 300) -> str | None:
    client = _client()
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
