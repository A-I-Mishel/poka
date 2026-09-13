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
            briefs, workflows, memory, meta routers + chatflow pipeline)
  |
  v
agent/  (budget, executor, prompts, providers, cascade, router,
          toolrun, planning, reflection, vision, workflows, runtime)
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
| `GROQ_API_KEY` | no | Groq fast-inference tier |
| `OPENROUTER_API_KEY` | no | OpenRouter fallback tiers (free models) |
| `PLUTO_AUTH_MODE` | no (`open`) | `open` = dev/trusted, `private` = login required |
| `PLUTO_ACCESS_TOKENS` | for private mode | Comma-separated access tokens |
| `PLUTO_USER_ID` | no | Pin a stable local/dev identity |
| `PLUTO_DATA_DIR` | no (`data/`) | Storage root override (tests use tmp) |
| `PLUTO_FRONTEND_ORIGIN` | on the API host | Allowed CORS origin(s) of the UI |
| `VITE_API_URL` | on Vercel | Public URL of the API (empty = same origin) |
| `PLUTO_KB_EMBED_MODEL` | no | Embedding model for document search (default `models/gemini-embedding-001`) |
| `GOOGLE_CLIENT_ID` | for Gmail | Google OAuth client ID (Desktop app) |
| `GOOGLE_CLIENT_SECRET` | for Gmail | Google OAuth client secret |
| `GOOGLE_REFRESH_TOKEN` | for Gmail | Refresh token from `scripts/get_google_refresh_token.py` |
| `PLUTO_MCP_SERVERS` | no | JSON list of MCP servers (stdio and/or remote URLs) |
| `PLUTO_MCP_ALLOW_TOOLS` | with MCP servers | Comma globs like `github.*,docs.search` (default deny) |

Locally these live in `.env` (gitignored). On Render/Vercel put them
under Environment Variables. Never commit keys.

## Authentication modes

- **open** (default): local/dev/trusted use. Identity is `PLUTO_USER_ID`
  when set, else the browser's stable `X-Pluto-Visitor` id (minted once
  into localStorage, so logged-out chats persist), else a per-request
  ephemeral id. Clients may send `Authorization: Bearer <token>`; it is
  verified only against `PLUTO_ACCESS_TOKENS`.
- **private**: only `PLUTO_USER_ID` or holders of a `PLUTO_ACCESS_TOKENS`
  token (sent as `Authorization: Bearer <token>`) are admitted.
  Everyone else gets HTTP 401. Tokens are compared with
  `secrets.compare_digest`, never logged, and only a hash-derived user
  ID is persisted.

## User accounts (login / signup)

`POST /api/auth/signup` and `POST /api/auth/login` (`{username,
password}`) issue opaque session tokens (Bearer from then on,
`GET /api/auth/me` shows who you are, `POST /api/auth/logout`
revokes). Usernames are 3–32 chars (`A–Z a–z 0–9 _ . -`, unique
case-insensitively); passwords are 8–128 chars, stored as
PBKDF2-HMAC-SHA256 (per-user salt, 200k iterations — never cleartext),
and only token hashes are persisted. Signup/login are per-IP
rate-limited. Each account gets a stable `acct-<hex>` id, so chats,
memory, uploads, and document vectors isolate per account
automatically — sign in on any device and your history is there.
Sessions work in both auth modes.

## Model configuration

Cascade (first live tier wins, failed tiers cool down):
1. Muse Spark 1.3 (OpenCode, Responses API, temperature 0.7)
2. Nemotron 3.5 Lightning (OpenCode free tier)
3. Nemotron 3 Ultra, Big Pickle, MiMo V2.5,
   Ling 3.0 Flash (OpenCode free tier, rotating promos;
   DeepSeek V4 Flash free retired Sep 2026 — now paid only)
4. Groq (fast inference; model via `GROQ_MODEL`)
5. Gemini 3.6 Flash (Google, free tier ~20 req/day)
6. Gemini 3.5 Flash (Google fallback)
7. OpenRouter Nemotron Ultra + Gemma + Nemotron Super + Nemotron 3.5
   + Gemma 26B + Ling Fin + Inkling Small + Laguna (free fallbacks)

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

Gmail (`search_gmail`, `read_gmail`, `create_gmail_draft`,
`send_gmail`): one configured account via Google OAuth (Desktop app
client + `scripts/get_google_refresh_token.py` for the refresh
token). Mail is untrusted DATA; sending is irreversible, so
`send_gmail` refuses without explicit user confirmation
(`confirm=true`) — drafts are the safe default. Without credentials
the tools report unconfigured instead of failing.

Calendar (`list_calendar_events`, `create_calendar_event`,
`delete_calendar_event`): same Google OAuth client (refresh token
must carry the calendar scope — re-run the helper after adding it).
Creating is low-risk; deletion needs `confirm=true`.

Database (`list_tables`, `describe_table`, `query_database`,
`import_csv_table`, `execute_sql`): per-user SQLite vault file, zero
setup or credentials. Reads are SELECT-only and capped; writes need
`confirm=true`; table names are validated identifiers and
ATTACH/DETACH are rejected.

MCP gateway (`list_mcp_tools`, `call_mcp_tool`): use tools from any
configured MCP server — stdio servers for local dev (need node/npx),
remote HTTP/SSE servers for hosted deploys. Servers come from
`PLUTO_MCP_SERVERS` (server secrets via named env vars, never
literals); `PLUTO_MCP_ALLOW_TOOLS` globs decide what the model may
touch (default deny). Third-party output is untrusted DATA; each call
opens a fresh session.

Sandboxed Python (`run_python`): pure computation only (arithmetic,
strings, collections, functions, `print` for output). No imports, no
files, no network, no `while` loops, no private/dunder access; loops
and `range()` are iteration-budgeted. Private mode only
(`PLUTO_AUTH_MODE=private`) — open mode is denied outright — plus its
own rate limit. This is a prompt-injection-grade sandbox, not a kernel
boundary: hosts needing hard isolation must containerize the API.

Document knowledge base (vector retrieval, answers "what do my
documents say"): text-bearing uploads (PDF/CSV) are chunked and
embedded at upload time (best-effort, never fails the upload) into the
uploader's vault (`kb.json`); the `search_documents` tool ranks chunks
by cosine similarity. Embeddings come from Gemini (`GEMINI_API_KEY`,
model via `PLUTO_KB_EMBED_MODEL`); per-user isolation holds — one
user's vectors are never searched for another. Heuristic memory
(regex facts + keyword overlap) is separate and answers "what has this
user told me before".

Workflows (saved fixed pipelines, `/api/workflows`): named,
owner-saved tool sequences run deterministically with no LLM planning
— steps execute in order through the normal tool funnel (budgets,
timeouts, STATUS markers). String args may embed `{{input}}`
(run-time input) and `{{steps.N.output}}` (earlier steps' reported
output); the first non-OK step stops the run. `send_gmail` is blocked,
and code/SQL/identifiers accept no step-output templates, so templated
tool output cannot become code injection or silent exfiltration.

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
   (builds the web UI and serves it from the API).
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
