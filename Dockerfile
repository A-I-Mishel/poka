# ---- Pluto web UI build ----
FROM node:24-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- Pluto API + serving ----
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY . ./
COPY --from=web /web/dist ./frontend/dist
# Accounts + chats + uploads live under PLUTO_DATA_DIR (default ./data).
# Without a mounted volume this directory dies with the container, so every
# restart wipes data/accounts.json: old session tokens 401 and /login fails
# with "Invalid username or password", forcing a fresh signup each time.
# Run with `-v pluto-data:/app/data` (or set PLUTO_DATA_DIR to a mounted
# path) for durable logins.
RUN mkdir -p /app/data
VOLUME ["/app/data"]
# Least privilege: the API needs no root (writes only to PLUTO_DATA_DIR
# and tmp). Named volumes inherit the image dir's appuser ownership;
# bind mounts keep host ownership — chown the host path to 10001 first.
RUN useradd -m -u 10001 appuser && chown -R appuser:appuser /app
USER appuser
# Hugging Face Spaces routes to 7860; other hosts override with $PORT.
EXPOSE 7860
# No curl in slim: stdlib-only probe of the public health endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD python -c "import os,sys,urllib.request; p=os.getenv('PORT','7860'); sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{p}/api/health', timeout=4).status==200 else 1)"
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
