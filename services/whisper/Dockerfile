# Self-hosted faster-whisper transcription service (WaveDesk P4.5).
FROM python:3.12-slim

# ffmpeg: faster-whisper decodes WhatsApp's opus/ogg voice notes through it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

EXPOSE 9010
HEALTHCHECK --interval=30s --timeout=5s --retries=5 \
    CMD curl -fs http://localhost:9010/health || exit 1

CMD ["python", "app.py"]
