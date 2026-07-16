"""App factory. Run locally with:
    uvicorn app.main:app --reload --port 8000
"""

from fastapi import FastAPI

# importing the api modules registers their handlers with the compat router
from app import compat
from app.api import (  # noqa: F401  (registration side effects)
    ai,
    analytics,
    assign,
    auth,
    canned,
    chats,
    contacts,
    groups,
    invites,
    labels,
    messages,
    monitoring,
    numbers,
    phase3,
    platform,
    send,
    teams,
    tickets,
    workspace,
)


def create_app() -> FastAPI:
    app = FastAPI(title="WaveDesk Backend", docs_url=None, redoc_url=None)
    app.include_router(compat.router)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    return app


def create_asgi():
    """Production entrypoint (socket.io wraps the FastAPI app):
    uvicorn --factory app.main:create_asgi"""
    from app import socketio_server

    return socketio_server.asgi_app(create_app())


app = create_app()
