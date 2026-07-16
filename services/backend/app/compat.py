"""Frappe-contract compatibility layer.

The SPA + packages/api-client speak Frappe's RPC dialect:

    GET/POST /api/method/<dotted.method.path>
    → 200 {"message": <return value>}   (or 4xx/5xx on error)
    cookie session auth via `sid`

This module gives the new backend the same surface: handlers register under
their dotted name; one catch-all route dispatches. Params merge query string,
form body, and JSON body (Frappe semantics). `allow_guest` mirrors
@frappe.whitelist(allow_guest=True).
"""

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import sessions
from app.db import get_sessionmaker


@dataclass
class Ctx:
    """Everything a handler needs — the moral equivalent of frappe.local."""

    request: Request
    response: Response
    db: Session
    params: dict[str, Any]
    sid: str | None
    session: dict | None = None

    @property
    def user_id(self) -> str | None:
        return self.session.get("user_id") if self.session else None

    @property
    def user_email(self) -> str | None:
        return self.session.get("email") if self.session else None


Handler = Callable[[Ctx], Any | Awaitable[Any]]

_REGISTRY: dict[str, tuple[Handler, bool]] = {}


def method(dotted: str, *, allow_guest: bool = False):
    """Register a handler under its Frappe-style dotted path."""

    def deco(fn: Handler) -> Handler:
        _REGISTRY[dotted] = (fn, allow_guest)
        return fn

    return deco


async def _params(request: Request) -> dict[str, Any]:
    params: dict[str, Any] = dict(request.query_params)
    ctype = request.headers.get("content-type", "")
    if "application/json" in ctype:
        try:
            body = await request.json()
            if isinstance(body, dict):
                params.update(body)
        except ValueError:
            pass
    elif "form" in ctype:
        form = await request.form()
        params.update({k: v for k, v in form.items() if isinstance(v, str)})
    return params


router = APIRouter()


@router.api_route("/api/method/{dotted:path}", methods=["GET", "POST"])
async def dispatch(dotted: str, request: Request) -> Response:
    entry = _REGISTRY.get(dotted)
    if entry is None:
        raise HTTPException(404, f"Method not found: {dotted}")
    handler, allow_guest = entry

    sid = request.cookies.get("sid")
    sess = sessions.get(sid)
    if not allow_guest and sess is None:
        raise HTTPException(401, "Not logged in")

    response = Response()
    db = get_sessionmaker()()
    try:
        ctx = Ctx(
            request=request,
            response=response,
            db=db,
            params=await _params(request),
            sid=sid,
            session=sess,
        )
        result = handler(ctx)
        if inspect.isawaitable(result):
            result = await result
        db.commit()
    except PermissionError as err:
        db.rollback()
        raise HTTPException(403, str(err)) from err
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    if isinstance(result, Response):
        return result  # raw responses (CSV downloads etc.) pass through
    out = JSONResponse({"message": result})
    # carry over cookies a handler set (login/logout)
    for header, value in response.raw_headers:
        if header == b"set-cookie":
            out.raw_headers.append((header, value))
    return out
