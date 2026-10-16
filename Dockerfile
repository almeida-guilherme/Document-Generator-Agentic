# The whole app in one image: the React front end is built in a first stage and served by FastAPI.
# Used by compose.yaml (see deploy/LIGHTSAIL.md); data lives in the /data volume, never in the image.

FROM node:22.23.2-bookworm-slim AS frontend
WORKDIR /frontend
COPY web/frontend/package.json web/frontend/package-lock.json ./
RUN npm ci
COPY web/frontend/ ./
RUN npm run build

FROM python:3.12.14-slim-bookworm
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PDD_DATA_DIR=/data
# ffmpeg cuts the audio for transcription; Graphviz draws the flowchart.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg graphviz \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 1000 pidi && mkdir /data && chown pidi /data
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
COPY --from=frontend /frontend/dist web/frontend/dist
USER pidi
EXPOSE 8000
# One process: the job queue runs in it (PDD_WORKERS threads). Caddy in front handles HTTPS.
CMD ["uvicorn", "web.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
