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
```

Dependency flow: frontend → backend → agent → services/tools →
storage/providers. Tools only accept opaque upload IDs; every model
call goes through the shared bounded executor; memory and tool output
are always labeled untrusted data in prompts.

## Installation

Requires Python 3.12 and Node 24.

```bash
pip install -r requirements.lock
uvicorn backend.main:app --port 8000   # API on http://localhost:8000
cd frontend && npm install && npm run dev   # UI on http://localhost:5173
```

`requirements.txt` holds the loose constraints; `requirements.lock`
is the hash-pinned build input (regenerate with
`uv pip compile --universal --generate-hashes --python-version 3.12 -o requirements.lock requirements.txt`;
`--universal` keeps platform markers like `pywin32` so Linux installs work).
CI, Docker, and Render all install from the lock.

Run the test suite (stubbed models, temp directories — no API quota
spent):

```bash
pip install pytest
python -m pytest tests/ -q
```

## Environment variables / secrets

| Variable | Required | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | yes (or Groq/OpenRouter key) | Google Gemini models (3.8/3.7/3.6 Flash main + 3.5 backup) |
| `GROQ_API_KEY` | no | Groq 120B strong fallback + 20B fast/simple lane (`GROQ_MODEL` / `GROQ_FAST_MODEL`) |
| `OPENROUTER_API_KEY` | no | OpenRouter Free Router emergency fallback (`openrouter/free`) |
| `MISTRAL_API_KEY` | no | Mistral free evaluation tier (no card, last resort) |
| `COHERE_API_KEY` | no | Cohere Command tier (direct key, OpenAI-compatible endpoint). Set `COHERE_MODEL=command-a-vision-07-2025` to also use it as backup vision lane behind Gemini |
| `PLUTO_AUTH_MODE` | no (`open`) | `open` = dev/trusted, `private` = login required |
| `PLUTO_ACCESS_TOKENS` | for private mode | Comma-separated access tokens |
| `PLUTO_USER_ID` | no | Pin a stable local/dev identity |
| `PLUTO_DATA_DIR` | no (`data/`) | Storage root override (tests use tmp) |
| `PLUTO_FRONTEND_ORIGIN` | on the API host | Allowed CORS origin(s) of the UI |
| `PLUTO_ALLOW_OPEN` | no (`false`) | Opt into public-host `open` mode (default fail-closed refuses to start) |
| `PLUTO_ALLOW_SHARED_VAULT` | no (`false`) | Opt into `PLUTO_USER_ID`+`open` sharing one vault on a public host |
| `PLUTO_ALLOW_MEMORY_LIMITER` | no (`false`) | Opt into per-process limits with `UVICORN_WORKERS>1` and no `REDIS_URL` |
| `VITE_API_URL` | on Vercel | Public URL of the API (empty = same origin) |
| `PLUTO_KB_EMBED_MODEL` | no | Embedding model for document search (default `models/gemini-embedding-001`) |
| `GOOGLE_CLIENT_ID` | for Gmail | Google OAuth client ID (Desktop app) |
| `GOOGLE_CLIENT_SECRET` | for Gmail | Google OAuth client secret |
| `GOOGLE_REFRESH_TOKEN` | for Gmail | Refresh token from `scripts/get_google_refresh_token.py` |
| `PLUTO_MCP_SERVERS` | no | JSON list of MCP servers (stdio and/or remote URLs) |
| `PLUTO_MCP_ALLOW_TOOLS` | with MCP servers | Comma globs like `github.*,docs.search` (default deny) |
| `R2_BUCKET` / `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` | for free-tier durability | Snapshot backend credentials (R2 or Supabase Storage S3 keys) |
| `R2_ACCOUNT_ID` | for R2 only | Builds the default R2 endpoint (omit for Supabase) |
| `SNAPSHOT_ENDPOINT_URL` | for non-R2 backends | e.g. `https://<ref>.storage.supabase.co/storage/v1/s3` |
| `SNAPSHOT_REGION` | for non-R2 backends | Region from the backend's S3 settings page |
| `SNAPSHOT_INTERVAL_SECONDS` | no (`10`) | Min seconds between snapshot uploads |
| `SNAPSHOT_ENABLED` | no (`true`) | `false` disables snapshots despite credentials |

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
password}`) issue opaque session tokens (`pluto_`-prefixed, Bearer
from then on, `GET /api/auth/me` shows who you are,
`POST /api/auth/logout` revokes). Usernames are 3–32 chars
(`A–Z a–z 0–9 _ . -`, unique case-insensitively); new passwords are
8–128 chars with a strength check (not your username, not a common
password, 3 of 4 character groups), stored as PBKDF2-HMAC-SHA256
(per-user salt, 200k iterations — never cleartext), and only token
hashes are persisted. Repeated failed logins lock the account for 15
minutes (HTTP 429). `POST /api/auth/change-password`
(`{current_password, new_password}`) rotates the credential and kills
every session, returning a fresh token; `GET /api/auth/sessions`
lists live sessions (this device flagged) and
`POST /api/auth/logout-all` revokes them all. Signup/login are
per-IP rate-limited. Each account gets a stable `acct-<hex>` id, so chats,
memory, uploads, and document vectors isolate per account
automatically — sign in on any device and your history is there.
Sessions work in both auth modes.

## Model configuration

Role-based tier tables (first live tier wins, failed tiers cool down).
Final answers use the synthesis table (Gemini-led; Groq Fast excluded as
cheap-only); dumb calls (classification, summaries, planning, reflection)
use the cheap table (Groq Fast first, saving Gemini quota); the full
cascade below is the escape hatch when synthesis is down (answers then
carry a degraded marker):
1. Gemini 3.8 Flash (Google main; override via `GEMINI_38_MODEL`)
2. Gemini 3.7 Flash (Google main; override via `GEMINI_37_MODEL`)
3. Gemini 3.6 Flash (Google main; override via `GEMINI_36_MODEL`)
4. Gemini 3.5 Flash (Google backup; override via `GEMINI_35_MODEL`)
5. Gemini 3.5 Flash Lite (fresh quota pool; override via `GEMINI_35_LITE_MODEL`)
6. Gemini 3.1 Flash Lite (older generation, last Gemini lane; override via `GEMINI_31_LITE_MODEL`)
7. Groq 120B (strong fallback; model via `GROQ_MODEL`)
8. Cohere Command (`COHERE_MODEL`; vision backup via `command-a-vision-07-2025`)
9. OpenRouter Nemotron 3 Ultra 550B (`nvidia/nemotron-3-ultra-550b-a55b:free`; reasoning lane)
10. OpenRouter Qwen 3.8 27B (`qwen/qwen3.8-27b:free` via `OPENROUTER_QWEN_MODEL`; trial Sep 2026)
11. OpenRouter GLM 5.2 (`z-ai/glm-5.2:free` via `OPENROUTER_GLM_MODEL`; reasoning trial Sep 2026)
12. OpenRouter Ling 3.0 Flash VL (`inclusionai/ling-3.0-flash-vl:free` via `OPENROUTER_LING_VL_MODEL`;
    vision-capable trial Sep 2026 — free vision fallback behind Gemini/Cohere)
13. OpenRouter Free Router (`openrouter/free`; smart auto-selection
    of a free model filtered by request features)
14. Mistral (free evaluation tier; `open-mistral-nemo` via `MISTRAL_MODEL` — last resort)

Cheap table (dumb calls): Groq Fast 20B (`GROQ_FAST_MODEL`) → Groq 120B → Mistral.
GitHub Models + NVIDIA removed (dead); other curated OpenRouter lanes
removed (Gemma/Super/3.5/26B/Ling-Fin/Laguna) — only Nemotron Ultra + Qwen/GLM/Ling
trial lanes (Sep 2026, remove if flaky) + Free Router kept.

OpenCode Zen free tier (Muse Spark 1.3 contributor-free, Nemotron
3.5/Ultra, Big Pickle, MiMo, Ling) retired Sep 2026 — provider now
returns `MissingSessionID` ("free tier can only be used in OpenCode")
for API calls. Paid Zen models remain usable via
`https://opencode.ai/zen/v1` if billing is added (re-add slugs in
`config.py`).

Per-task temperatures apply when a tier answers (creative 0.85,
factual/research lower). Deep Mode (UI toggle) enables planning +
self-reflection at the cost of extra calls. If a tier dies mid-turn,
the next live tier continues the same turn with collected tool results
kept — planning, tool rounds, and final synthesis all fail over, so
work is never restarted from scratch.

Input understanding (`services/normalize.py`, single source): typo
correction + creation-verb canonicalization (`turn`/`convert`/`make` →
`create`) feed the router, tool binding, and teaching detection, so
`craete`, `convrt`, `pyton`, `documnet` keep their intent. Typo
metadata rides each answer (`corrections`, `route_confidence`); reads
auto-correct with a note, writes confirm via approvals. Mine new
vocabulary with `python scripts/mine_fallthrough.py` or
`GET /api/ops/router` (scrubbed, no PII) — grow the synonym table,
never ad-hoc keyword branches.

Answer quality: synthesis stays Gemini-led and quality-first (weak
lanes — Groq Fast, Mistral, Free Router — answer
only when quality tiers are down, marked `fallback: degraded`);
grounding applies to every tier and synthesis; research drafts earn
one cheap-tier reflection pass (150+ chars).

## Tools

File tools accept opaque upload IDs only — never filesystem paths.
Results carry `STATUS=` markers (`OK/EMPTY/FAILED/INVALID/DENIED/
DEGRADED`) so failures can't be mistaken for data. PDF reads are
page-marked and bounded (upload cap re-checked at read time, malformed
input yields structured failures); CSV reads are byte-, column-, and
row-capped before pandas runs, with a controlled `csv_inspect` op set
(no arbitrary code execution); presentations are slide-capped (50) with
truncation notes and documents are validated by reopening before
delivery. Standalone web pages (`.html`, full document or fragment)
are saved as downloadable artifacts that open in any browser.

Gmail (`search_gmail`, `read_gmail`, `create_gmail_draft`,
`send_gmail`): one configured account via Google OAuth (Desktop app
client + `scripts/get_google_refresh_token.py` for the refresh
token). Mail is untrusted DATA; sending is irreversible, so
`send_gmail` runs only after the user approves a server-minted,
single-use approval token in the UI (`/api/approvals`) — drafts are
the safe default. Without credentials the tools report unconfigured
instead of failing.

Calendar (`list_calendar_events`, `create_calendar_event`,
`delete_calendar_event`): same Google OAuth client (refresh token
must carry the calendar scope — re-run the helper after adding it).
Creating is low-risk; deletion needs a UI approval token.

Database (`list_tables`, `describe_table`, `query_database`,
`import_csv_table`, `execute_sql`): per-user SQLite vault file, zero
setup or credentials. Reads are SELECT-only and capped; writes and
CSV imports need a UI approval token; table names are validated
identifiers and ATTACH/DETACH are rejected.

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
audit (`pip-audit`) is advisory — it reports known vulnerabilities
without failing CI.

## Known limitations

- Free-tier models are rate-limited (Gemini ~20 req/day). The
  OpenCode Zen free tier was retired Sep 2026 (`MissingSessionID`);
  only paid Zen models remain usable with billing (see Model
  configuration).
- Image-only (scanned) PDFs report as such; on-device OCR needs an
  engine that isn't bundled.
- Vision works on Gemini tiers; other tiers answer from text with an
  honest inability note.
- In-memory rate limiter is per-process (documented; Redis-swappable).
- Provider HTTP calls carry native timeouts; a hung sync SDK call still
  occupies one shared pool thread until it returns, but callers always
  regain control at the deadline (see `agent/executor.py`).
