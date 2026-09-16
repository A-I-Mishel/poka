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
# Hugging Face Spaces routes to 7860; other hosts override with $PORT.
EXPOSE 7860
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
