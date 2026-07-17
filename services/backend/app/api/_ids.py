"""Shared helper: parse a client-supplied UUID, turning a malformed value into
a clean 400 instead of an uncaught ValueError → 500."""

import uuid

from fastapi import HTTPException


def parse_uuid(value: str | None, field: str = "id") -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(400, f"Invalid {field}") from None
