# WaveDesk backend — FastAPI + SQLAlchemy + Postgres (+ socket.io realtime).
# All deps ship binary wheels (psycopg[binary] bundles libpq), so slim needs no
# compiler. Config is env-only (WD_*); see app/config.py.
FROM python:3.12-slim

WORKDIR /srv
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY pyproject.toml ./
COPY app ./app
# alembic.ini + migrations/ ship in the image so `alembic upgrade head` runs at
# deploy time (the migrations/ dir is read by the alembic CLI, not imported).
COPY alembic.ini ./
COPY migrations ./migrations
RUN pip install --upgrade pip && pip install .

EXPOSE 8000

# Default = the web process (REST + socket.io). The RQ worker that drains the
# wa:events consumer + queued sender/webhook jobs runs from the SAME image with
# a different command, e.g.:  rq worker default short long
CMD ["uvicorn", "--factory", "app.main:create_asgi", "--host", "0.0.0.0", "--port", "8000"]
