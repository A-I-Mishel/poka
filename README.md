# Poka — Smart Task Agent

Poka is a multi-purpose AI assistant (Streamlit web app) for students and
professionals: chat with file attachments, web research with citations,
PDF/CSV analysis, PowerPoint and Word generation, and persistent
per-user memory — backed by a cascading multi-model agent.

## Architecture

```
app.py  (Streamlit UI: chat, composer, sidebar, downloads)
  |
  v
services/  (identity, auth, storage, files, ratelimit, limits,
            context_budget, tokens, timeutil, vision)
  |
  v
agent.py  (4-tier cascade, tool loop, planning, reflection, budgets)
  |
  v
tools/  (web_search, read_pdf, read_pdf_page, analyze_csv, csv_inspect,
         create_pptx, build_presentation, create_docx, build_document)
memory_engine.py  (structured per-user memory)
ui/theme.py  (visual theme)
```

UI → services → agent → tools/storage. The UI never touches the
filesystem directly for user data; tools only accept opaque upload IDs.

## Installation

Requires Python 3.12.

```bash
pip install -r requirements.txt
pip install pytest          # for tests only
streamlit run app.py        # open http://localhost:8501
```

## Environment variables / secrets

| Variable | Required | Purpose |
|---|---|---|
| `OPENCODE_API_KEY` | yes (or Gemini key) | Tier 1–2 models via OpenCode |
| `GEMINI_API_KEY` | yes (or OpenCode key) | Tier 3–4 Google Gemini models |
| `POKA_AUTH_MODE` | no (`open`) | `open` = dev/trusted, `private` = login required |
| `POKA_ACCESS_TOKENS` | for private mode | Comma-separated access tokens |
| `POKA_USER_ID` | no | Pin a stable local/dev identity |
| `POKA_DATA_DIR` | no (`data/`) | Storage root override (tests use tmp) |

Locally these live in `.env` (gitignored). On Streamlit Cloud put them
under Settings → Secrets. Never commit keys; `.env` and
`.streamlit/secrets.toml` are gitignored.

## Authentication modes

- **open** (default): local/dev/trusted use. Identity chain is
  `POKA_USER_ID` → logged-in OIDC viewer → browser link token →
  ephemeral session. Link tokens are anonymous, never equivalent to login.
- **private**: only `POKA_USER_ID`, logged-in OIDC viewers, or holders of
  a `POKA_ACCESS_TOKENS` token (sign-in form or `?token=` URL) are
  admitted. Everyone else sees the sign-in screen. No password database:
  tokens are compared with `secrets.compare_digest`, never logged, and
  only a hash-derived user ID is persisted.

## Model configuration

Cascade (first live tier wins, failed tiers cool down):
1. Muse Spark 1.3 (OpenCode, temperature 0.7)
2. Nemotron 3.5 Lightning (OpenCode free tier)
3. Gemini 3.6 Flash (Google, free tier ~20 req/day)
4. Gemini 3.5 Flash (Google fallback)

Per-task temperatures apply when a tier answers (creative 0.85,
factual/research lower). Deep Mode (sidebar toggle) enables planning +
self-reflection at the cost of extra calls.

## Tools

File tools accept opaque upload IDs only — never filesystem paths.
Results carry `STATUS=` markers (`OK/EMPTY/FAILED/INVALID/DENIED/
DEGRADED`) so failures can't be mistaken for data. PDF reads are
page-marked and bounded; CSV reads are row-capped with a controlled
`csv_inspect` op set (no arbitrary code execution); presentations and
documents are validated by reopening before delivery.

## Storage architecture

Per-user vaults under `data/users/<safe-id>/`: `chats.json`,
`memory.md`, `structured.json`, `uploads/` + `uploads.json`,
`outputs/` + `outputs.json`. All writes are atomic (unique tmp +
replace) with per-file locks; corrupt files are quarantined with a
warning instead of silently resetting. Staged uploads older than 7 days
and unreferenced by any chat are pruned once per session.

## Security model

- Per-user isolation for chats, memory, uploads, outputs, and memory
  facts (semantic retrieval is per-user only; no global vector index).
- Path traversal rejected at every boundary; storage names generated.
- Rate limits per user (chat/search/upload/generate/deep).
- Request/tool/model budgets bound every request.
- Untrusted content (web/PDF/CSV/OCR/image/memory) is delimited DATA,
  never instructions; memory is injected in an isolated section.
- Logs carry request IDs, tiers, and counters — never keys, tokens,
  passwords, or document contents.

## Deployment

Streamlit Community Cloud: push `main`, set entry point `app.py`,
Python 3.12, add secrets. The free tier sleeps when idle and its disk
is ephemeral (chats/files persist on machines with real disks).

## Tests

```bash
python -m pytest tests/ -q
```

All tests use stubbed models and temp directories — no API quota spent.
GitHub Actions runs compile + pytest on every push (dependency audit is
advisory).

## Known limitations

- Free-tier models are rate-limited (Gemini ~20 req/day) and free
  OpenCode models change availability without notice.
- Image-only (scanned) PDFs report as such; on-device OCR needs an
  engine that isn't bundled.
- Vision works on Gemini tiers; other tiers answer from text with an
  honest inability note.
- Link-token identity is shareable by URL by design (open mode only).
- In-memory rate limiter is per-process (documented; Redis-swappable).
- Hung provider calls abandon their worker thread after timeout (caller
  always regains control; documented in `agent._call_bounded`).
