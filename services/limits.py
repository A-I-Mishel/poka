"""Centralized safety and resource limits.

Every magic number for uploads, tool output, and timeouts lives here so
behavior is consistent and easy to audit. No other module should hard-code
these values.
"""

# Uploads
MAX_UPLOAD_BYTES: int = 200 * 1024 * 1024
ALLOWED_UPLOAD_EXTS: frozenset = frozenset({
    "pdf", "csv", "tsv",
    "png", "jpg", "jpeg", "webp", "gif", "bmp",
    "txt", "md", "markdown", "log", "json",
    "html", "htm", "xhtml", "shtml", "xml", "svg",
    "yaml", "yml", "toml", "ini", "cfg", "conf",
    "css", "scss", "less",
    "js", "mjs", "cjs", "jsx", "ts", "mts", "tsx",
    "py", "pyi", "java", "c", "h", "cpp", "hpp", "cc",
    "cs", "go", "rs", "php", "rb", "swift", "kt", "kts",
    "scala", "pl", "lua", "sh", "bash", "zsh", "bat", "cmd",
    "ps1", "sql", "r", "jl", "vue", "svelte",
    "docx", "pptx", "xlsx",
    "zip",
    "doc", "ppt", "xls", "rtf", "odt", "ods", "odp",
})

# Per-user storage exhaustion controls (checked BEFORE writes/parsing).
MAX_UPLOADS_PER_USER: int = 100
MAX_USER_BYTES: int = 1024 * 1024 * 1024
MAX_OUTPUT_AGE_DAYS: int = 30

# CSV parse guards (all checked BEFORE pandas runs).
MAX_CSV_COLUMNS: int = 1000
MAX_CSV_PARSE_BYTES: int = 25 * 1024 * 1024

# Presentation generation guard (checked BEFORE expensive building).
MAX_PPTX_SLIDES: int = 50
MAX_PPTX_BULLETS_PER_SLIDE: int = 200

# Document generation guard (checked BEFORE expensive building).
MAX_DOCX_PARAGRAPHS: int = 1000

# Make-tool generation guard (create_pdf/create_doc/create_markdown share
# the lightweight-markdown subset; blocks capped like docx builders).
MAX_MAKE_BLOCKS: int = 300

# Tool input/output caps
MAX_PDF_PAGES: int = 200
MAX_PDF_CHARS: int = 12000
MAX_DOCUMENT_CHARS: int = 12000
MAX_CSV_ROWS: int = 50000
MAX_SEARCH_CHARS: int = 6000

# ZIP archive reading (stdlib zipfile, list + extract text-like members).
# Zip-bomb guards are checked BEFORE extraction: entry count, total
# uncompressed size, and per-file size. Inner files reuse the document
# text caps above; only text-like members are extracted, never executed.
MAX_ZIP_FILES: int = 100
MAX_ZIP_UNCOMPRESSED_BYTES: int = 50 * 1024 * 1024
MAX_ZIP_FILE_BYTES: int = 5 * 1024 * 1024
MAX_ZIP_LISTED: int = 200

# Legacy document fallback (best-effort stdlib extraction, no new deps).
# OLE .doc/.ppt/.xls strings fallback and RTF stripping are lossy by
# nature; output carries a fidelity note so models never mistake it
# for exact formatting.
MAX_LEGACY_STRINGS_CHARS: int = 12000

# Scanned-PDF OCR (embedded-image extraction via pypdf + optional
# pytesseract). No new system deps: when the OCR binary is absent the
# tool reports honestly and points at the Gemini vision workaround.
MAX_OCR_PAGES: int = 5

# Saved workflow pipelines (services/workflows.py + agent/workflows.py).
# Pipelines are owner-saved fixed tool sequences; caps keep registries
# small and rendered args bounded (templates resolve untrusted step
# output, so post-render args are re-capped, never silently truncated).
MAX_WORKFLOWS_PER_USER: int = 50
MAX_WORKFLOW_STEPS: int = 10
MAX_WORKFLOW_NAME_CHARS: int = 80
MAX_WORKFLOW_DESC_CHARS: int = 500
MAX_WORKFLOW_ARG_CHARS: int = 2000
MAX_WORKFLOW_INPUT_CHARS: int = 2000

# Sandboxed code execution (services.codeexec via tools.python_tool).
# Code/output caps keep snippets and transcripts small; the iteration
# budget bounds `for`/comprehension/range workloads (see codeexec).
# Wall-clock timeout bounds giant-int/CPU burns the AST check cannot see.
MAX_PYTHON_CODE_CHARS: int = 4000
MAX_PYTHON_OUTPUT_CHARS: int = 4000
MAX_PYTHON_ITERATIONS: int = 100000
MAX_PYTHON_EXEC_SECONDS: float = 10.0

# Per-user code workspace (services.workspace via tools.workspace_tool).
# Private-mode writes + execution; list/read stay per-user isolated.
# Quotas checked BEFORE writes so a runaway model call fails fast.
MAX_WORKSPACE_FILES: int = 100
MAX_WORKSPACE_BYTES: int = 50 * 1024 * 1024
MAX_WORKSPACE_FILE_BYTES: int = 1 * 1024 * 1024
MAX_WORKSPACE_READ_CHARS: int = 20000
MAX_WORKSPACE_WRITE_CHARS: int = 100000
MAX_WORKSPACE_PATH_CHARS: int = 200

# Real code execution (services.coderun via tools.coderun_tool).
# Private-mode only (trusted owner). Subprocess with timeout, cwd locked
# to the user's workspace, minimal env, capped output. Hosts needing
# hard isolation must containerize the API process.
MAX_CODE_FILE_CHARS: int = 20000
MAX_CODE_OUTPUT_CHARS: int = 12000
MAX_CODE_EXEC_SECONDS: float = 30.0
MAX_CODE_ARGS_CHARS: int = 1000

# Execution bounds (seconds)
MODEL_TIMEOUT_SECONDS: float = 90.0
# First-response deadline: a tier that emits no token within this window
# is abandoned and the cascade falls through to the next tier. Applies to
# every model call (classify, answer, tools, reflection, vision).
# 12s: free tiers routinely need 5-10s for the first token; 3s caused
# constant false-timeout churn, wasted quota, and latency.
FIRST_TOKEN_TIMEOUT_SECONDS: float = 12.0
TOOL_TIMEOUT_SECONDS: float = 90.0
MCP_TIMEOUT_SECONDS: float = 60.0
PROBE_TIMEOUT_SECONDS: float = 20.0

# Output cap (tokens) — unbounded completions on 8B lanes ramble and burn budget.
# ponytail: universal 1800 tok (~5 slides with boxes); split to 1500/3000 per
# deep_mode when 1800 measurably truncates research answers.
MODEL_MAX_TOKENS: int = 1800
MODEL_MAX_TOKENS_DEEP: int = 3000
# ponytail: OpenRouter free lanes queue longer — 20s first-token vs 12s for Groq/Gemini
FIRST_TOKEN_TIMEOUT_OPENROUTER_SECONDS: float = 20.0

# Request budgets (per single user message)
MAX_LLM_CALLS_PER_REQUEST: int = 12
MAX_TOOL_CALLS_PER_REQUEST: int = 8
MAX_SEARCH_CALLS_PER_REQUEST: int = 2
MAX_REFLECTION_CALLS: int = 1
MAX_PLANNING_CALLS: int = 1
MAX_TOTAL_REQUEST_TIME: float = 300.0

# Self-reflection tuning (agent/reflection.py)
# Short draft or task type triggers re-critique; keywords hint at a failed
# answer worth one more pass.
REFLECT_SHORT_DRAFT_CHARS: int = 80
REFLECT_FAILURE_KEYWORDS: tuple = ("error", "failed", "unable to", "could not")
# The draft is fed to the critic in a bounded window (chat history stays
# untruncated): critic quality holds while long research drafts no longer
# blow the prompt. A rewrite is only accepted when it is substantive —
# at least REFLECT_MIN_IMPROVE_RATIO x the draft length (guards against
# a shorter, lossy rewrite winning).
REFLECT_DRAFT_WINDOW_CHARS: int = 4000
REFLECT_MIN_IMPROVE_RATIO: float = 0.5

# Plan-then-execute (agent/planning.py): the plan text is injected into
# the execution prompt verbatim, so it is capped to keep a runaway plan
# from crowding the context budget.
PLAN_MAX_CHARS: int = 4000

# Context budgets (tokens, approximated — see services.tokens)
CONTEXT_MAX_TOKENS: int = 24000
CTX_HISTORY_TOKENS: int = 6000
CTX_MEMORY_TOKENS: int = 2000
CTX_SUMMARY_TOKENS: int = 2000
CTX_EXTERNAL_TOKENS: int = 4000
MAX_TOOL_RESULT_TOKENS: int = 3000
MAX_EXTERNAL_TOKENS: int = 12000
MAX_QUERY_CHARS: int = 300

# Rate limits: action -> (max calls, window seconds), scoped per limiting
# identity (stable user ID, or client IP for ephemeral open-mode visitors).
RATE_LIMITS: dict = {
    "chat": (100, 3600.0),
    "search": (60, 3600.0),
    "upload": (30, 3600.0),
    "generate": (20, 3600.0),
    "deep": (20, 3600.0),
    "kb_search": (60, 3600.0),
    "gmail": (30, 3600.0),
    "calendar": (30, 3600.0),
    "database": (30, 3600.0),
    "code": (20, 3600.0),
    "workflow": (20, 3600.0),
    "mcp": (20, 3600.0),
    # Signup/login attempts per client IP (brute-force friction).
    "auth": (20, 3600.0),
}

# Knowledge base (vector retrieval over user documents). All tunables
# live here — never hardcoded at call sites.
KB_CHUNK_CHARS: int = 1200
KB_CHUNK_OVERLAP: int = 150
KB_MAX_CHUNKS_PER_DOC: int = 40
KB_MAX_DOC_BYTES: int = 400000
# kb.json growth guard: vectors are stored as full floats and each
# search loads the whole file, so per-user totals stay bounded (~100
# docs). Ingest beyond either cap degrades to {"ingested": False,
# "reason": "kb-full"} (never fails the upload).
KB_MAX_DOCS_PER_USER: int = 100
KB_MAX_TOTAL_CHUNKS_PER_USER: int = 2000
KB_TOP_K: int = 5
KB_MAX_SNIPPET_CHARS: int = 12000
KB_INGEST_EXTS: frozenset = frozenset({"pdf", "csv", "tsv", "txt", "md", "markdown", "log", "json", "html", "htm", "xhtml", "shtml", "xml", "svg", "yaml", "yml", "toml", "ini", "cfg", "conf", "css", "scss", "less", "js", "mjs", "cjs", "jsx", "ts", "mts", "tsx", "py", "pyi", "java", "c", "h", "cpp", "hpp", "cc", "cs", "go", "rs", "php", "rb", "swift", "kt", "kts", "scala", "pl", "lua", "sh", "bash", "zsh", "bat", "cmd", "ps1", "sql", "r", "jl", "vue", "svelte", "docx", "pptx", "xlsx", "zip", "doc", "ppt", "xls", "rtf", "odt", "ods", "odp", "png", "jpg", "jpeg", "webp", "gif", "bmp"})
# Image ingest cap: full-file bytes (not the 400 KB text cap — a truncated
# image is undecodable). Pixel gate lives in services/kb._image_text.
MAX_KB_IMAGE_BYTES: int = 5 * 1024 * 1024

# Research briefs (services/research.py): source and text caps for the
# brief/docx surface. Display and docx text stay bounded the same way
# the storage cleaners bound titles — no literal limits at call sites.
RESEARCH_MAX_SOURCES: int = 6
RESEARCH_TITLE_CHARS: int = 120
RESEARCH_MARKDOWN_CHARS: int = 20000
RESEARCH_DISPLAY_TITLE_CHARS: int = 60
RESEARCH_SCOPE_NAME_CHARS: int = 30
RESEARCH_DOCX_ERROR_CHARS: int = 500

# Tier cooldowns (agent cascade): driven by classify_provider_error kinds.
# Timeouts are congestion, not outage (brief cool, 2nd consecutive strike);
# quota errors mean hours of darkness (daily resets — no 10-minute re-probes);
# auth/invalid config never heals by retrying (long); server/network/unknown
# are transient (default window).
TIER_COOLDOWN_TIMEOUT_SECONDS: float = 60.0
TIER_COOLDOWN_TRANSIENT_SECONDS: float = 600.0
TIER_COOLDOWN_QUOTA_SECONDS: float = 6 * 3600.0
TIER_COOLDOWN_PERMANENT_SECONDS: float = 3600.0
TIMEOUT_STRIKES_BEFORE_COOL: int = 2

# Tool-loop round caps: normal requests stop early; Deep Mode chains
# tools until the model stops asking, bounded by the deep request
# budget below (plus the unchanged wall-clock deadline).
MAX_TOOL_ROUNDS: int = 4
MAX_DEEP_TOOL_ROUNDS: int = 12
MAX_DEEP_LLM_CALLS: int = 30
MAX_DEEP_TOOL_CALLS: int = 20

# Project context (explicit user-controlled per-project text).
# Conservative: operational instructions, not a document store (~1000
# tokens against a 24k budget alongside memory and history).
MAX_PROJECT_CONTEXT_CHARS: int = 4000

# Research brief bounds (user-owned research records).
MAX_BRIEF_QUERY_CHARS: int = 500
MAX_BRIEF_EXCERPT_CHARS: int = 4000

# Generation spec bounds (opaque reproducibility records, never code).
# Per-string and total caps keep specs from becoming a document store.
MAX_SPEC_STRING_CHARS: int = 100_000
MAX_SPEC_TOTAL_CHARS: int = 200_000

# Storage hygiene
MAX_FILENAME_LEN: int = 100
UPLOAD_ID_RE: str = r"^[0-9a-f]{16}$"

# Hygiene pass cadence: prune_stale_uploads (7d unreferenced) and
# prune_stale_outputs (30d) run at most this often per user per process,
# triggered from the request lifecycle (backend.deps). Thresholds are in
# days, so hourly-or-daily is plenty; per-request would waste a chats +
# registry load on every call.
STORAGE_HYGIENE_INTERVAL_SECONDS: float = 6 * 3600.0

# Username/password accounts (services.accounts): host-level cap so an
# open signup endpoint cannot grow the registry without bound.
MAX_ACCOUNTS_PER_HOST: int = 1000

# Composer attachments (per single user message). 5 total keeps tool
# hints small (contents are never stuffed; tools read on demand within
# existing budgets) with headroom under the 8-record storage backstop.
# Images are capped at 3 to match the vision fast-path batch size.
MAX_ATTACHMENTS_PER_MESSAGE: int = 5
MAX_IMAGE_ATTACHMENTS: int = 3

# UI display truncations (single source of truth — no [:38]/[:120]/[:200]
# literals elsewhere in production code; tests may use literals).
MAX_CHAT_TITLE_CHARS: int = 38
MAX_DISPLAY_NAME_CHARS: int = 120
MAX_ERROR_SNIPPET_CHARS: int = 200

# Structured presentation builder bounds (single source of truth).
# create_pptx caps via MAX_PPTX_SLIDES / MAX_PPTX_BULLETS_PER_SLIDE above;
# build_presentation reuses the same slide cap plus these layout caps.
PPTX_BUILD_MAX_TITLE_CHARS: int = 80
PPTX_BUILD_MAX_BULLET_CHARS: int = 160
PPTX_BUILD_MAX_BULLETS_PER_CHUNK: int = 7
PPTX_BUILD_MAX_TABLE_ROWS: int = 12
PPTX_BUILD_MAX_TABLE_COLS: int = 6
PPTX_BUILD_MAX_SUBTITLE_CHARS: int = 120

# UI layout hints for API consumers (image preview width, composer height).
# Single source of truth for width=/height= literals.
UI_IMAGE_PREVIEW_WIDTH: int = 320
UI_TEXT_AREA_HEIGHT: int = 80
UI_HTML_SHIM_HEIGHT: int = 0

# Local logic checker (tools.logic_tool): pure stdlib, zero model calls.
# 2**n rows explode, so 6 vars = 64 rows max; formulas and premise
# counts stay small so output fits the tool transcript budget.
MAX_LOGIC_VARS: int = 6
MAX_LOGIC_FORMULA_CHARS: int = 500
MAX_LOGIC_PREMISES: int = 10

# Lite self-RAG (services.kb + tools.kb_search_tool): score-based,
# zero-extra-LLM-call retry. Vector scores are cosine 0..1; lexical
# scores are integer term-overlap counts. A top hit below these means
# "weak" -> one simplified-query retry, then merge (never more than
# two kb.search calls per tool call, protecting Gemini embed quota).
KB_WEAK_VECTOR_SCORE: float = 0.25
KB_WEAK_LEXICAL_MIN: int = 2
