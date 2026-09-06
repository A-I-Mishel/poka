"""Per-user persistent storage (chats, notes, structured memory).

Layout:
    data/users/<safe-user-id>/chats.json
    data/users/<safe-user-id>/memory.md
    data/users/<safe-user-id>/structured.json

DATA_ROOT defaults to ./data and can be overridden with POKA_DATA_DIR
(useful for tests). All writes are atomic (tmp + os.replace). Corrupt
files are quarantined next to the original and reported as warnings
instead of silently resetting user data.
"""

import contextlib
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple
from urllib.parse import urlparse

from services.obs import event as obs_event

MAX_STORED_CHATS: int = 20
MAX_MSGS_PER_CHAT: int = 100
ATTACH_KINDS = ("pdf", "csv", "image")
MAX_PROJECT_NAME_LEN: int = 60
PROJECTS_VERSION: int = 1

_ID16_RE = re.compile(r"^[0-9a-f]{16}$")


def is_valid_id(value: Any) -> bool:
    """True for stable 16-hex IDs (conversations, projects, uploads)."""
    return isinstance(value, str) and _ID16_RE.match(value) is not None


def new_conversation_id() -> str:
    """Generate a fresh stable conversation/project ID."""
    return uuid.uuid4().hex[:16]
RESPONSE_MODES = ("fast", "deep")
MAX_MODEL_NAME_LEN: int = 64
MAX_TOOL_NAMES: int = 20
MAX_TOOL_NAME_LEN: int = 64
MAX_SOURCES: int = 6
MAX_SOURCE_TITLE_LEN: int = 120
MAX_SOURCE_URL_LEN: int = 500
MAX_SOURCE_DOMAIN_LEN: int = 120
_SOURCE_URL_SCHEMES = ("http", "https")

# Generation-spec tool allowlist: tool name -> (artifact kind, exact
# permitted input keys). Specs reproduce tool calls; anything outside
# this table is not a valid spec.
_SPEC_TOOLS: Dict[str, Any] = {
    "create_pptx": ("pptx", {"topic", "content"}),
    "build_presentation": ("pptx", {"spec_json"}),
    "create_docx": ("docx", {"title", "content"}),
    "build_document": ("docx", {"title", "markdown_text"}),
}


class StorageError(Exception):
    """Raised when a storage path or operation is unsafe or fails."""


def data_root() -> Path:
    """Return the configured data root directory."""
    return Path(os.getenv("POKA_DATA_DIR", "data"))


def sanitize_user_key(raw: Any) -> str:
    """Make a user ID safe for use as a single directory name."""
    text = str(raw or "").strip()
    if not text or ".." in text or "/" in text or "\\" in text:
        raise StorageError("Refusing to resolve storage for a path-like user ID.")
    text = re.sub(r"[^A-Za-z0-9_.-]", "_", text).strip(" .")
    if not text:
        raise StorageError("Refusing to resolve storage for an empty user ID.")
    return text[:64]


def user_dir(user_id: str) -> Path:
    """Resolve a user's directory, rejecting any traversal outside users/."""
    key = sanitize_user_key(user_id)
    base = (data_root() / "users").resolve()
    base.mkdir(parents=True, exist_ok=True)
    candidate = (base / key).resolve()
    if candidate != base and base not in candidate.parents:
        raise StorageError("User storage path escapes the users directory.")
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


def _tmp_path(path: Path) -> Path:
    """Unique tmp sibling so concurrent writers never share one file."""
    token = f"{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex[:8]}"
    return path.with_name(f"{path.name}.{token}.tmp")


_locks_guard = threading.Lock()
_locks: Dict[str, threading.Lock] = {}


@contextlib.contextmanager
def path_lock(path: Path) -> Iterator[None]:
    """Per-file mutex so concurrent readers/writers never race on Windows."""
    try:
        key = str(path.resolve())
    except OSError:
        key = str(path.absolute())
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _locks[key] = lock
    with lock:
        yield


def atomic_replace(src: Path, dst: Path, attempts: int = 5) -> None:
    """os.replace with retries: Windows AV/indexer locks briefly race us."""
    last: Optional[Exception] = None
    for _ in range(attempts):
        try:
            os.replace(src, dst)
            return
        except OSError as e:
            last = e
            time.sleep(0.05)
    assert last is not None
    raise last


def _read_json(path: Path) -> Tuple[Any, bool]:
    """Read JSON, returning (data, was_corrupt). Missing file -> (None, False).

    Error classes are strictly separated:
    - FileNotFoundError -> missing state, (None, False).
    - JSON malformation (ValueError) -> corruption: the file is
      quarantined next to the original and (None, True) is returned.
    - PermissionError / other OSError -> infrastructure failure: raised
      as StorageError (never quarantined, never converted to empty
      state). Callers must surface this instead of silently resetting.
    """
    try:
        with path_lock(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f), False
    except FileNotFoundError:
        return None, False
    except PermissionError as e:
        obs_event("storage.read", status="error", reason="permission", file=path.name)
        raise StorageError(f"Cannot read {path.name}: permission denied.") from e
    except OSError as e:
        obs_event("storage.read", status="error", reason="io", file=path.name)
        raise StorageError(f"Cannot read {path.name}: storage failure ({e}).") from e
    except ValueError:
        try:
            backup = path.with_name(f"{path.stem}.corrupt-{int(time.time())}{path.suffix}")
            os.replace(path, backup)
        except OSError:
            pass
        obs_event("storage.quarantine", file=path.name)
        return None, True


def _write_json(path: Path, payload: Any) -> None:
    """Write JSON atomically via unique-tmp + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _tmp_path(path)
    try:
        with path_lock(path):
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            atomic_replace(tmp_path, path)
    except OSError as e:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        obs_event("storage.write", status="error", file=path.name)
        raise StorageError(f"Could not persist {path.name}: {e}") from e


def _clean_attachment(value: Any) -> Optional[Dict[str, str]]:
    if not isinstance(value, dict):
        return None
    upload_id = value.get("id")
    kind = value.get("kind")
    name = value.get("name", "")
    if not isinstance(upload_id, str) or not upload_id:
        return None
    if kind not in ATTACH_KINDS:
        return None
    if not isinstance(name, str):
        return None
    return {"id": upload_id, "kind": kind, "name": name[:120]}


def _clean_artifact(value: Any) -> Optional[Dict[str, str]]:
    """Keep a message→artifact link ({id,kind,name}); None when unusable."""
    if not isinstance(value, dict):
        return None
    file_id = value.get("id")
    kind = value.get("kind")
    name = value.get("name", "")
    if not isinstance(file_id, str) or not file_id:
        return None
    if kind not in ("pptx", "docx", "file"):
        return None
    if not isinstance(name, str) or not name:
        return None
    return {"id": file_id, "kind": kind, "name": name[:120]}


def _clean_tool_names(value: Any) -> Optional[List[str]]:
    """Keep a list of safe tool names; None when absent or unusable."""
    if not isinstance(value, list):
        return None
    names = [
        t[:MAX_TOOL_NAME_LEN]
        for t in value
        if isinstance(t, str) and t
    ]
    if not names:
        return None
    return names[:MAX_TOOL_NAMES]


def clean_source_record(value: Any) -> Optional[Dict[str, str]]:
    """Validate one persisted source record; None when unusable.

    Requires an http(s) URL without whitespace/control characters.
    Title falls back to the domain; domain is recomputed from the URL
    so stored records cannot smuggle mismatched metadata.
    """
    if not isinstance(value, dict):
        return None
    url = value.get("url", "")
    if not isinstance(url, str):
        return None
    url = url.strip()
    if not url or len(url) > MAX_SOURCE_URL_LEN:
        return None
    if any(ch in url for ch in (" ", "\t", "\n", "\r", "\x00")):
        return None
    try:
        parts = urlparse(url)
    except Exception:
        return None
    if parts.scheme.lower() not in _SOURCE_URL_SCHEMES or not parts.netloc:
        return None
    title = value.get("title", "")
    title = str(title).strip()[:MAX_SOURCE_TITLE_LEN] if isinstance(title, str) else ""
    domain = parts.netloc.lower()[:MAX_SOURCE_DOMAIN_LEN]
    return {"title": title or domain, "url": url, "domain": domain}


def clean_generation_spec(value: Any) -> Optional[Dict[str, Any]]:
    """Validate an artifact generation spec; None when unusable.

    A spec is bounded opaque DATA ({kind, tool, input, created}) that a
    future phase may use to reproduce a generation. Unknown tools,
    kind/tool mismatches, unknown or non-string fields, oversize
    payloads, and bad timestamps are all rejected — never coerced —
    so an invalid spec can never masquerade as a reproducible one.
    """
    from services.limits import MAX_SPEC_STRING_CHARS, MAX_SPEC_TOTAL_CHARS

    if not isinstance(value, dict):
        return None
    kind = value.get("kind", "")
    tool = value.get("tool", "")
    if kind not in ("pptx", "docx") or not isinstance(tool, str):
        return None
    expected = _SPEC_TOOLS.get(tool)
    if expected is None or expected[0] != kind:
        return None
    raw_input = value.get("input", None)
    if not isinstance(raw_input, dict):
        return None
    if set(raw_input.keys()) != expected[1]:
        return None
    cleaned_input: Dict[str, str] = {}
    total = 0
    for key in sorted(expected[1]):
        field = raw_input.get(key, "")
        if not isinstance(field, str) or not field.strip():
            return None
        if len(field) > MAX_SPEC_STRING_CHARS:
            return None
        total += len(field)
        if total > MAX_SPEC_TOTAL_CHARS:
            return None
        cleaned_input[key] = field
    created = value.get("created", None)
    if (not isinstance(created, (int, float)) or isinstance(created, bool)
            or not created >= 0):
        return None
    return {"kind": kind, "tool": tool, "input": cleaned_input,
            "created": float(created)}


def clean_messages(messages: Any) -> List[Dict[str, Any]]:
    """Validate/trim a message list.

    Preserves role/content/time/image/images/attachments plus optional
    assistant metadata (model/mode/searched/search_executed/tools/sources)
    and assistant artifact links. Unknown keys are dropped; legacy
    messages without metadata pass through unchanged.
    """
    cleaned: List[Dict[str, Any]] = []
    if isinstance(messages, list):
        for m in messages:
            if (
                not isinstance(m, dict)
                or m.get("role") not in ("user", "assistant")
                or not isinstance(m.get("content"), str)
            ):
                continue
            entry: Dict[str, Any] = {"role": m["role"], "content": m["content"]}
            if isinstance(m.get("time"), str):
                entry["time"] = m["time"]
            if isinstance(m.get("image"), str):
                entry["image"] = m["image"]
            if isinstance(m.get("images"), list):
                images = [str(p) for p in m["images"] if isinstance(p, str)]
                if images:
                    entry["images"] = images[:8]
            if isinstance(m.get("attachments"), list):
                atts = [_clean_attachment(a) for a in m["attachments"]]
                atts = [a for a in atts if a is not None]
                if atts:
                    entry["attachments"] = atts[:8]
            if isinstance(m.get("artifacts"), list):
                arts = [_clean_artifact(a) for a in m["artifacts"]]
                arts = [a for a in arts if a is not None]
                if arts:
                    entry["artifacts"] = arts[:8]
            if isinstance(m.get("model"), str) and m["model"]:
                entry["model"] = m["model"][:MAX_MODEL_NAME_LEN]
            if m.get("mode") in RESPONSE_MODES:
                entry["mode"] = m["mode"]
            if isinstance(m.get("searched"), bool):
                entry["searched"] = m["searched"]
            if isinstance(m.get("search_executed"), bool):
                entry["search_executed"] = m["search_executed"]
            if isinstance(m.get("sources"), list):
                srcs = [clean_source_record(s) for s in m["sources"]]
                srcs = [s for s in srcs if s is not None]
                if srcs:
                    entry["sources"] = srcs[:MAX_SOURCES]
            cleaned_tools = _clean_tool_names(m.get("tools"))
            if cleaned_tools is not None:
                entry["tools"] = cleaned_tools
            cleaned.append(entry)
    return cleaned[-MAX_MSGS_PER_CHAT:]


def _clean_chat_record(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    record: Dict[str, Any] = {
        "title": str(value.get("title", "Untitled"))[:60],
        "messages": clean_messages(value.get("messages", [])),
    }
    if is_valid_id(value.get("id")):
        record["id"] = value["id"]
    if is_valid_id(value.get("project_id")):
        record["project_id"] = value["project_id"]
    return record


def find_chat_by_id(chats: Any, chat_id: Any) -> Optional[Dict[str, Any]]:
    """Resolve a conversation by stable ID within one user's list.

    Returns a copy, or None for malformed IDs and misses. Never raises.
    Index-based access remains for existing UI paths; no new feature
    may persist list indexes as references.
    """
    if not is_valid_id(chat_id):
        return None
    if not isinstance(chats, list):
        return None
    for chat in chats:
        if isinstance(chat, dict) and chat.get("id") == chat_id:
            return dict(chat)
    return None


def _clean_brief_record(value: Any) -> Optional[Dict[str, Any]]:
    """Validate one brief record; None when identity/content fields fail.

    Query must be present and bounded; excerpt must be a bounded string;
    sources keep only valid records (capped); project_id keeps only
    valid-format IDs (existence is checked at creation, orphans load
    as-is like conversations). Bad created coerces to 0.0.
    """
    from services.limits import MAX_BRIEF_EXCERPT_CHARS, MAX_BRIEF_QUERY_CHARS

    if not isinstance(value, dict):
        return None
    bid = value.get("id")
    if not is_valid_id(bid):
        return None
    query = value.get("query", "")
    if not isinstance(query, str) or not query.strip():
        return None
    excerpt = value.get("excerpt", "")
    if not isinstance(excerpt, str):
        return None
    raw_sources = value.get("sources", [])
    if not isinstance(raw_sources, list):
        raw_sources = []
    kept = []
    for item in raw_sources:
        cleaned = clean_source_record(item)
        if cleaned is not None:
            kept.append(cleaned)
        if len(kept) >= MAX_SOURCES:
            break
    created = value.get("created", 0.0)
    if not isinstance(created, (int, float)) or isinstance(created, bool) \
            or not created >= 0:
        created = 0.0
    record: Dict[str, Any] = {
        "id": bid,
        "query": query.strip()[:MAX_BRIEF_QUERY_CHARS],
        "sources": kept,
        "excerpt": excerpt[:MAX_BRIEF_EXCERPT_CHARS],
        "created": float(created),
    }
    if is_valid_id(value.get("project_id")):
        record["project_id"] = value["project_id"]
    return record


def _clean_project_record(value: Any) -> Optional[Dict[str, Any]]:
    """Validate one project record; None when identity-bearing fields fail.

    Bad id/name drops the record; bad created/archived coerce to safe
    defaults so one malformed entry never sinks the whole registry.
    """
    if not isinstance(value, dict):
        return None
    pid = value.get("id")
    name = value.get("name", "")
    if not is_valid_id(pid):
        return None
    if not isinstance(name, str) or not name.strip():
        return None
    created = value.get("created", 0.0)
    if not isinstance(created, (int, float)) or not created >= 0:
        created = 0.0
    archived = value.get("archived", False)
    return {
        "id": pid,
        "name": name.strip()[:MAX_PROJECT_NAME_LEN],
        "created": float(created),
        "archived": archived is True,
    }


class UserStore:
    """All persistent state owned by one user ID."""

    def __init__(self, user_id: str) -> None:
        self.user_id: str = sanitize_user_key(user_id)
        self.root: Path = user_dir(self.user_id)
        self.chats_path: Path = self.root / "chats.json"
        self.memory_path: Path = self.root / "memory.md"
        self.structured_path: Path = self.root / "structured.json"
        self.projects_path: Path = self.root / "projects.json"
        self.migrate_legacy()

    # -- chats -------------------------------------------------
    def load_chats(self) -> Tuple[Dict[str, Any], List[str]]:
        """Return ({"chats": [...], "current": [...]}, warnings)."""
        warnings: List[str] = []
        try:
            data, corrupt = _read_json(self.chats_path)
        except StorageError as e:
            # Infrastructure failure (e.g. permissions): report it, keep
            # the stored data untouched, and run an empty session.
            return {"chats": [], "current": []}, [f"Chat history unavailable ({e})"]
        if corrupt:
            warnings.append("Chat history was corrupted; a backup copy was kept and history was reset.")
        if not isinstance(data, dict):
            return {"chats": [], "current": []}, warnings
        chats: List[Dict[str, Any]] = []
        raw = data.get("chats", [])
        if isinstance(raw, list):
            for c in raw[:MAX_STORED_CHATS]:
                record = _clean_chat_record(c)
                if record is not None:
                    chats.append(record)
        return {"chats": chats, "current": clean_messages(data.get("current", []))}, warnings

    def save_chats(self, chats: Any, current: Any) -> None:
        """Persist chats + open conversation. Raises StorageError on failure."""
        stored: List[Dict[str, Any]] = []
        if isinstance(chats, list):
            for c in chats[:MAX_STORED_CHATS]:
                record = _clean_chat_record(c)
                if record is not None:
                    stored.append(record)
        _write_json(self.chats_path, {"chats": stored, "current": clean_messages(current)})

    # -- projects --------------------------------------------------
    # Per-user registry; absence of project_id on a chat means Personal
    # (no fake Personal record is ever created). Mutations hold the
    # per-file lock across read-modify-write; concurrent same-field
    # edits are last-writer-wins.

    def load_projects(self) -> Tuple[Dict[str, Any], List[str]]:
        """Return ({"version": 1, "projects": [...]}, warnings).

        A missing file is normal for existing users (no warning).
        Corrupt files are quarantined centrally with a warning.
        """
        warnings: List[str] = []
        try:
            data, corrupt = _read_json(self.projects_path)
        except StorageError as e:
            return {"version": PROJECTS_VERSION, "projects": []}, [
                f"Projects unavailable ({e})"
            ]
        if corrupt:
            warnings.append("Projects file was corrupted; a backup copy was kept.")
        if not isinstance(data, dict):
            return {"version": PROJECTS_VERSION, "projects": []}, warnings
        raw = data.get("projects", [])
        projects: List[Dict[str, Any]] = []
        if isinstance(raw, list):
            for entry in raw:
                record = _clean_project_record(entry)
                if record is not None:
                    projects.append(record)
        return {"version": PROJECTS_VERSION, "projects": projects}, warnings

    def save_projects(self, projects: Any) -> None:
        """Persist the project list (cleaned). Raises StorageError."""
        stored: List[Dict[str, Any]] = []
        if isinstance(projects, list):
            for entry in projects:
                record = _clean_project_record(entry)
                if record is not None:
                    stored.append(record)
        _write_json(self.projects_path, {"version": PROJECTS_VERSION, "projects": stored})

    def _mutate_projects(self, fn: Any) -> Any:
        """Read-modify-write the registry under one lock hold."""
        with path_lock(self.projects_path):
            data, _ = _read_json(self.projects_path)
            raw = data.get("projects", []) if isinstance(data, dict) else []
            projects = [
                r for r in
                (_clean_project_record(e) for e in raw)
                if r is not None
            ] if isinstance(raw, list) else []
            result, updated = fn(projects)
            _write_json(self.projects_path, {"version": PROJECTS_VERSION, "projects": updated})
            return result

    @staticmethod
    def _check_project_name(name: Any) -> str:
        """Sanitize a project name; ValueError when empty."""
        cleaned = str(name or "").strip()
        if not cleaned:
            raise ValueError("Project name must not be empty.")
        return cleaned[:MAX_PROJECT_NAME_LEN]

    def create_project(self, name: Any) -> Dict[str, Any]:
        """Create a project; returns the stored record. ValueError on bad name."""
        cleaned = self._check_project_name(name)

        def _add(projects: List[Dict[str, Any]]) -> Any:
            record = {
                "id": new_conversation_id(),
                "name": cleaned,
                "created": time.time(),
                "archived": False,
            }
            return dict(record), projects + [record]

        return self._mutate_projects(_add)

    def rename_project(self, project_id: Any, name: Any) -> bool:
        """Rename a project; False for unknown IDs. ValueError on bad name."""
        cleaned = self._check_project_name(name)
        if not is_valid_id(project_id):
            return False

        def _rename(projects: List[Dict[str, Any]]) -> Any:
            for entry in projects:
                if entry["id"] == project_id:
                    entry["name"] = cleaned
                    return True, projects
            return False, projects

        return bool(self._mutate_projects(_rename))

    def get_project(self, project_id: Any) -> Optional[Dict[str, Any]]:
        """Return a copy of one project, or None (unknown/malformed IDs)."""
        if not is_valid_id(project_id):
            return None
        data, _ = self.load_projects()
        for entry in data["projects"]:
            if entry["id"] == project_id:
                return dict(entry)
        return None

    def list_projects(self, include_archived: bool = False) -> List[Dict[str, Any]]:
        """Projects in creation order; archived excluded unless asked."""
        data, _ = self.load_projects()
        return [
            dict(entry) for entry in data["projects"]
            if include_archived or not entry.get("archived", False)
        ]

    def archive_project(self, project_id: Any) -> bool:
        """Archive a project (idempotent); memberships are kept. False if unknown."""
        if not is_valid_id(project_id):
            return False

        def _archive(projects: List[Dict[str, Any]]) -> Any:
            for entry in projects:
                if entry["id"] == project_id:
                    entry["archived"] = True
                    return True, projects
            return False, projects

        return bool(self._mutate_projects(_archive))

    # -- research briefs -----------------------------------------------
    # Bounded user-owned research records. Briefs reference projects by
    # ID (validated at creation); listing filters without a separate
    # index. No UI, search, or generation behavior is attached here.

    def _briefs_path(self) -> Path:
        return self.root / "briefs.json"

    def load_briefs(self) -> Tuple[Dict[str, Any], List[str]]:
        """Return ({"version": 1, "briefs": [...]}, warnings).

        A missing file is normal (no warning). Corrupt files are
        quarantined centrally with a warning.
        """
        warnings: List[str] = []
        try:
            data, corrupt = _read_json(self._briefs_path())
        except StorageError as e:
            return {"version": 1, "briefs": []}, [
                f"Briefs unavailable ({e})"
            ]
        if corrupt:
            warnings.append("Briefs file was corrupted; a backup copy was kept.")
        if not isinstance(data, dict):
            return {"version": 1, "briefs": []}, warnings
        raw = data.get("briefs", [])
        briefs: List[Dict[str, Any]] = []
        if isinstance(raw, list):
            for entry in raw:
                record = _clean_brief_record(entry)
                if record is not None:
                    briefs.append(record)
        return {"version": 1, "briefs": briefs}, warnings

    def save_briefs(self, briefs: Any) -> None:
        """Persist the brief list (cleaned). Raises StorageError."""
        stored: List[Dict[str, Any]] = []
        if isinstance(briefs, list):
            for entry in briefs:
                record = _clean_brief_record(entry)
                if record is not None:
                    stored.append(record)
        _write_json(self._briefs_path(), {"version": 1, "briefs": stored})

    def _mutate_briefs(self, fn: Any) -> Any:
        """Read-modify-write the registry under one lock hold."""
        with path_lock(self._briefs_path()):
            data, _ = _read_json(self._briefs_path())
            raw = data.get("briefs", []) if isinstance(data, dict) else []
            briefs = [
                r for r in
                (_clean_brief_record(e) for e in raw)
                if r is not None
            ] if isinstance(raw, list) else []
            result, updated = fn(briefs)
            _write_json(self._briefs_path(), {"version": 1, "briefs": updated})
            return result

    def create_brief(self, query: Any, sources: Any, excerpt: Any = "",
                     project_id: Any = None) -> Dict[str, Any]:
        """Create a brief; returns the stored record.

        Raises ValueError for an empty/oversize query, non-string or
        oversize excerpt, non-list sources, or an unknown project.
        Source items that fail validation are dropped (never fatal).
        """
        from services.limits import MAX_BRIEF_EXCERPT_CHARS, MAX_BRIEF_QUERY_CHARS

        if not isinstance(query, str) or not query.strip():
            raise ValueError("Brief query must not be empty.")
        if len(query) > MAX_BRIEF_QUERY_CHARS:
            raise ValueError(
                f"Brief query is limited to {MAX_BRIEF_QUERY_CHARS} characters."
            )
        if not isinstance(excerpt, str):
            raise ValueError("Brief excerpt must be a string.")
        if len(excerpt) > MAX_BRIEF_EXCERPT_CHARS:
            raise ValueError(
                f"Brief excerpt is limited to {MAX_BRIEF_EXCERPT_CHARS} characters."
            )
        if not isinstance(sources, list):
            raise ValueError("Brief sources must be a list.")
        pid: Optional[str] = None
        if project_id is not None:
            if not is_valid_id(project_id) or self.get_project(project_id) is None:
                raise ValueError("Unknown project.")
            pid = str(project_id)

        def _add(briefs: List[Dict[str, Any]]) -> Any:
            record: Dict[str, Any] = {
                "id": new_conversation_id(),
                "query": query.strip(),
                "sources": [],
                "excerpt": excerpt,
                "created": time.time(),
            }
            for item in sources:
                cleaned = clean_source_record(item)
                if cleaned is not None:
                    record["sources"].append(cleaned)
                if len(record["sources"]) >= MAX_SOURCES:
                    break
            if pid is not None:
                record["project_id"] = pid
            return dict(record), briefs + [record]

        return self._mutate_briefs(_add)

    def get_brief(self, brief_id: Any) -> Optional[Dict[str, Any]]:
        """Return a copy of one brief, or None (unknown/malformed IDs)."""
        if not is_valid_id(brief_id):
            return None
        data, _ = self.load_briefs()
        for entry in data["briefs"]:
            if entry["id"] == brief_id:
                return dict(entry)
        return None

    def list_briefs(self, project_id: Any = None) -> List[Dict[str, Any]]:
        """Briefs newest-first; optional exact project_id filter.

        project_id=None lists everything (no fake Personal bucket).
        """
        data, _ = self.load_briefs()
        matching = [
            dict(entry) for entry in data["briefs"]
            if project_id is None or entry.get("project_id") == project_id
        ]
        matching.sort(key=lambda e: e.get("created", 0.0), reverse=True)
        return matching

    def delete_brief(self, brief_id: Any) -> bool:
        """Delete one brief; False for unknown IDs. No other lifecycle."""
        if not is_valid_id(brief_id):
            return False

        def _drop(briefs: List[Dict[str, Any]]) -> Any:
            kept = [e for e in briefs if e["id"] != brief_id]
            return len(kept) != len(briefs), kept

        return bool(self._mutate_briefs(_drop))

    # -- project context ---------------------------------------------
    # Explicit user-controlled per-project text. Stored outside
    # projects.json so context edits never rewrite the registry, and
    # never merged into global memory files.

    def project_context_path(self, project_id: Any) -> Path:
        """Resolve this project's context.md, validating ownership first.

        The project must exist in the caller's own registry; the path is
        then built from the validated 16-hex ID (never raw input) and
        verified contained. Raises StorageError otherwise.
        """
        record = self.get_project(project_id)
        if record is None:
            raise StorageError("Unknown project.")
        candidate = (self.root / "projects" / str(record["id"]) / "context.md")
        try:
            resolved = candidate.resolve()
            base = self.root.resolve()
        except OSError as e:
            raise StorageError(f"Cannot resolve project path ({e}).") from e
        if resolved != base and base not in resolved.parents:
            raise StorageError("Project storage path escapes the user vault.")
        return candidate

    def load_project_context(self, project_id: Any) -> str:
        """Return project context text, "" when missing/unreadable.

        Never raises for missing, undecodable, or unreadable files
        (fail safe); unknown projects raise StorageError via path
        resolution.
        """
        path = self.project_context_path(project_id)
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except FileNotFoundError:
            return ""
        except OSError:
            return ""
        try:
            return raw.decode("utf-8")
        except UnicodeError:
            return ""

    def save_project_context(self, project_id: Any, text: Any) -> None:
        """Persist project context atomically. Raises on failure/oversize."""
        from services.limits import MAX_PROJECT_CONTEXT_CHARS

        content = str(text or "")
        if len(content) > MAX_PROJECT_CONTEXT_CHARS:
            raise ValueError(
                f"Project context is limited to {MAX_PROJECT_CONTEXT_CHARS} "
                "characters."
            )
        path = self.project_context_path(project_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = _tmp_path(path)
        try:
            with path_lock(path):
                with open(tmp_path, "w", encoding="utf-8") as f:
                    f.write(content)
                atomic_replace(tmp_path, path)
        except OSError as e:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            raise StorageError(f"Could not save project context: {e}") from e

    # -- memory notes ------------------------------------------
    def load_notes(self) -> str:
        try:
            with open(self.memory_path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return ""
        except PermissionError as e:
            raise StorageError("Cannot read memory notes: permission denied.") from e
        except OSError as e:
            raise StorageError(f"Cannot read memory notes: storage failure ({e}).") from e

    def save_notes(self, text: str) -> None:
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = _tmp_path(self.memory_path)
        try:
            with path_lock(self.memory_path):
                with open(tmp_path, "w", encoding="utf-8") as f:
                    f.write(text)
                atomic_replace(tmp_path, self.memory_path)
        except OSError as e:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            raise StorageError(f"Could not save memory notes: {e}") from e

    # -- structured memory --------------------------------------
    def load_structured(self) -> Tuple[Dict[str, Any], List[str]]:
        """Return (memory dict, warnings) with guaranteed default keys."""
        try:
            data, corrupt = _read_json(self.structured_path)
        except StorageError as e:
            return (
                {"preferences": {}, "facts": [], "past_tasks": [], "user_name": None},
                [f"Structured memory unavailable ({e})"],
            )
        warnings = (
            ["Structured memory was corrupted; a backup copy was kept."] if corrupt else []
        )
        blank: Dict[str, Any] = {"preferences": {}, "facts": [], "past_tasks": [], "user_name": None}
        if not isinstance(data, dict):
            return blank, warnings
        for key, default in blank.items():
            data.setdefault(key, default)
        if not isinstance(data.get("facts"), list):
            data["facts"] = []
        return data, warnings

    def save_structured(self, mem: Dict[str, Any]) -> None:
        if not isinstance(mem, dict):
            raise StorageError("Refusing to save non-dict structured memory.")
        _write_json(self.structured_path, mem)

    # -- legacy migration ----------------------------------------
    def migrate_legacy(self) -> bool:
        """One-time import from pre-isolation global files. Returns True if moved."""
        if self.chats_path.exists() or self.memory_path.exists() or self.structured_path.exists():
            return False
        moved = False
        legacy_chats = Path("memory") / "chats.json"
        if legacy_chats.exists():
            try:
                data, _ = _read_json(legacy_chats)
            except StorageError:
                data = None
            if isinstance(data, dict) and (data.get("chats") or data.get("current")):
                try:
                    self.save_chats(data.get("chats", []), data.get("current", []))
                    moved = True
                except StorageError:
                    pass
        legacy_notes = Path("memory") / "memory.md"
        if legacy_notes.exists():
            try:
                self.save_notes(legacy_notes.read_text(encoding="utf-8"))
                moved = True
            except OSError:
                pass
        legacy_structured = Path("structured_memory.json")
        if legacy_structured.exists():
            try:
                data, _ = _read_json(legacy_structured)
            except StorageError:
                data = None
            if isinstance(data, dict) and data:
                try:
                    self.save_structured(data)
                    moved = True
                except StorageError:
                    pass
        return moved
