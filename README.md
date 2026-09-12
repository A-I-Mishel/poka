# Pluto — Smart Task Agent

Pluto is a multi-purpose AI assistant (web app + FastAPI backend)
for students and professionals: chat with file attachments, web
research with citations, PDF/CSV analysis, PowerPoint and Word
generation, and persistent per-user memory — backed by a cascading
multi-model agent.

## Architecture

```
frontend/  (Vite + vanilla JS UI, deployed on Vercel)
  |
  v  (HTTP /api, VITE_API_URL points at the backend)
backend/  (FastAPI: chat, chats, uploads, artifacts, projects,
           briefs, memory, meta routers + chatflow pipeline)
  |
  v
agent/  (budget, executor, prompts, providers, cascade, router,
         toolrun, planning, reflection, vision, runtime)
  |
  v
services/  (auth, identity, storage, files, memory, secrets, limits,
            ratelimit, context, context_budget, tokens, timeutil, vision)
  |
  v
tools/  (web_search, read_pdf, read_pdf_page, analyze_csv, csv_inspect,
         create_pptx, build_presentation, create_docx, build_document,
         gating shared pre-generation gate)
config.py  (tier construction, temperatures; secrets via services.secrets)
memory_engine.py  (compat alias of services.memory)
```

Dependency flow: frontend → backend → agent → services/tools →
storage/providers. Tools only accept opaque upload IDs; every model
call goes through the shared bounded executor; memory and tool output
are always labeled untrusted data in prompts.

## Installation

Requires Python 3.12 and Node 24.

```bash
pip install -r requirements.txt
uvicorn backend.main:app --port 8000   # API on http://localhost:8000
cd frontend && npm install && npm run dev   # UI on http://localhost:5173
```

Run the test suite (stubbed models, temp directories — no API quota
spent):

```bash
pip install pytest
python -m pytest tests/ -q
```

## Environment variables / secrets

| Variable | Required | Purpose |
|---|---|---|
| `OPENCODE_API_KEY` | yes (or Gemini key) | Tier 1–2 models via OpenCode |
| `GEMINI_API_KEY` | yes (or OpenCode key) | Tier 3–4 Google Gemini models |
| `PLUTO_AUTH_MODE` | no (`open`) | `open` = dev/trusted, `private` = login required |
| `PLUTO_ACCESS_TOKENS` | for private mode | Comma-separated access tokens |
| `PLUTO_USER_ID` | no | Pin a stable local/dev identity |
| `PLUTO_DATA_DIR` | no (`data/`) | Storage root override (tests use tmp) |
| `PLUTO_FRONTEND_ORIGIN` | on the API host | Allowed CORS origin(s) of the UI |
| `VITE_API_URL` | on Vercel | Public URL of the API (empty = same origin) |
| `PLUTO_KB_EMBED_MODEL` | no | Embedding model for document search (default `models/gemini-embedding-001`) |

Locally these live in `.env` (gitignored). On Render/Vercel put them
under Environment Variables. Never commit keys.

## Authentication modes

- **open** (default): local/dev/trusted use. Identity is `PLUTO_USER_ID`
  when set, else a per-request ephemeral id. Clients may send
  `Authorization: Bearer <token>`; it is verified only against
  `PLUTO_ACCESS_TOKENS`.
- **private**: only `PLUTO_USER_ID` or holders of a `PLUTO_ACCESS_TOKENS`
  token (sent as `Authorization: Bearer <token>`) are admitted.
  Everyone else gets HTTP 401. Tokens are compared with
  `secrets.compare_digest`, never logged, and only a hash-derived user
  ID is persisted.

## Model configuration

Cascade (first live tier wins, failed tiers cool down):
1. Muse Spark 1.3 (OpenCode, temperature 0.7)
2. Nemotron 3.5 Lightning (OpenCode free tier)
3. Gemini 3.6 Flash (Google, free tier ~20 req/day)
4. Gemini 3.5 Flash (Google fallback)

Per-task temperatures apply when a tier answers (creative 0.85,
factual/research lower). Deep Mode (UI toggle) enables planning +
self-reflection at the cost of extra calls.

## Tools

File tools accept opaque upload IDs only — never filesystem paths.
Results carry `STATUS=` markers (`OK/EMPTY/FAILED/INVALID/DENIED/
DEGRADED`) so failures can't be mistaken for data. PDF reads are
page-marked and bounded (upload cap re-checked at read time, malformed
input yields structured failures); CSV reads are byte-, column-, and
row-capped before pandas runs, with a controlled `csv_inspect` op set
(no arbitrary code execution); presentations are slide-capped (50) with
truncation notes and documents are validated by reopening before
delivery.

Document knowledge base (vector retrieval, answers "what do my
documents say"): text-bearing uploads (PDF/CSV) are chunked and
embedded at upload time (best-effort, never fails the upload) into the
uploader's vault (`kb.json`); the `search_documents` tool ranks chunks
by cosine similarity. Embeddings come from Gemini (`GEMINI_API_KEY`,
model via `PLUTO_KB_EMBED_MODEL`); per-user isolation holds — one
user's vectors are never searched for another. Heuristic memory
(regex facts + keyword overlap) is separate and answers "what has this
user told me before".

## Storage architecture

Per-user vaults under `data/users/<safe-id>/`: `chats.json`,
`memory.md`, `structured.json`, `uploads/` + `uploads.json`,
`outputs/` + `outputs.json`. All writes are atomic (unique tmp +
replace) with per-file locks; corrupt files are quarantined with a
warning instead of silently resetting. Staged uploads older than 7 days
and unreferenced by any chat are pruned once per session, as are
generated outputs older than 30 days. Upload quotas (100 files / 1 GiB
per user) are enforced before writes; permission/infrastructure
failures raise instead of masquerading as corruption.

## Security model

- Per-user isolation for chats, memory, uploads, outputs, memory
  facts, and document vectors (heuristic keyword-overlap retrieval and
  vector search are both per-user only).
- Path traversal rejected at every boundary; storage names generated.
- Rate limits per limiting identity (chat/search/upload/generate/deep):
  stable user ID when known, client IP for ephemeral open-mode visitors.
- Request/tool/model budgets bound every request.
- Untrusted content (web/PDF/CSV/OCR/image/memory) is delimited DATA,
  never instructions; memory is injected in an isolated section.
- Logs carry request IDs, tiers, and counters — never keys, tokens,
  passwords, or document contents.

## Deployment

- **API**: Render via `render.yaml` blueprint
  (`uvicorn backend.main:app`), or any Python host / the `Dockerfile`
  (builds the React UI and serves it from the API).
- **UI**: Vercel from `frontend/` (Vite). Set `VITE_API_URL` to the
  public API URL and `PLUTO_FRONTEND_ORIGIN` on the API host to the
  Vercel URL.
- Public deployments must set `PLUTO_AUTH_MODE=private` plus
  `PLUTO_ACCESS_TOKENS`: the default `open` mode is for local/dev/
  trusted use only.

## Tests

```bash
python -m pytest tests/ -q
```

All tests use stubbed models and temp directories — no API quota spent.
GitHub Actions runs compile + pytest on every push; the dependency
audit (`pip-audit`) is blocking — a known vulnerability fails CI.

## Known limitations

- Free-tier models are rate-limited (Gemini ~20 req/day) and free
  OpenCode models change availability without notice.
- Image-only (scanned) PDFs report as such; on-device OCR needs an
  engine that isn't bundled.
- Vision works on Gemini tiers; other tiers answer from text with an
  honest inability note.
- In-memory rate limiter is per-process (documented; Redis-swappable).
- Provider HTTP calls carry native timeouts; a hung sync SDK call still
  occupies one shared pool thread until it returns, but callers always
  regain control at the deadline (see `agent/executor.py`).
