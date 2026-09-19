"""UserStore: all persistent state owned by one user ID."""

import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from services.storage.cleaners import (
    _clean_brief_record,
    _clean_chat_record,
    _clean_project_record,
    _clean_workflow_record,
    clean_messages,
    clean_source_record,
)
from services.storage.ids import (
    MAX_PROJECT_NAME_LEN,
    MAX_SOURCES,
    MAX_STORED_CHATS,
    PROJECTS_VERSION,
    StorageError,
    WorkflowNotFoundError,
    is_valid_id,
    new_conversation_id,
)
from services.storage.io import (
    _read_json,
    _tmp_path,
    _write_json,
    atomic_replace,
    path_lock,
)
from services.storage.paths import sanitize_user_key, user_dir


class UserStore:
    """All persistent state owned by one user ID."""

    def __init__(self, user_id: str, run_migration: bool = True) -> None:
        self.user_id: str = sanitize_user_key(user_id)
        self.root: Path = user_dir(self.user_id, create=False)
        self.chats_path: Path = self.root / "chats.json"
        self.memory_path: Path = self.root / "memory.md"
        self.structured_path: Path = self.root / "structured.json"
        self.projects_path: Path = self.root / "projects.json"
        if run_migration:
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

    def _mutate_chats(self, fn: Any) -> Any:
        """Read-modify-write the chats file under one lock hold."""
        with path_lock(self.chats_path):
            data, _ = _read_json(self.chats_path)
            result = fn(data)
            _write_json(self.chats_path, result)
        # Invalidate store caches for this user
        from backend.deps import invalidate_store_caches
        invalidate_store_caches(self.user_id)
        return result

    def save_chats(self, chats: Any, current: Any) -> None:
        """Persist chats + open conversation. Raises StorageError on failure."""
        stored: List[Dict[str, Any]] = []
        if isinstance(chats, list):
            for c in chats[:MAX_STORED_CHATS]:
                record = _clean_chat_record(c)
                if record is not None:
                    stored.append(record)
        _write_json(self.chats_path, {"chats": stored, "current": clean_messages(current)})
        # Invalidate store caches for this user
        from backend.deps import invalidate_store_caches
        invalidate_store_caches(self.user_id)

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

    # -- workflows -------------------------------------------------
    # Owner-saved fixed tool pipelines (services/workflows.py validates
    # step semantics; these methods only persist cleaned records).

    def _workflows_path(self) -> Path:
        return self.root / "workflows.json"

    def load_workflows(self) -> Tuple[Dict[str, Any], List[str]]:
        """Return ({"version": 1, "workflows": [...]}, warnings).

        A missing file is normal (no warning). Corrupt files are
        quarantined centrally with a warning; malformed records are
        dropped (a bad step drops its record — see
        _clean_workflow_record).
        """
        warnings: List[str] = []
        try:
            data, corrupt = _read_json(self._workflows_path())
        except StorageError as e:
            return {"version": 1, "workflows": []}, [
                f"Workflows unavailable ({e})"
            ]
        if corrupt:
            warnings.append("Workflows file was corrupted; a backup copy was kept.")
        if not isinstance(data, dict):
            return {"version": 1, "workflows": []}, warnings
        raw = data.get("workflows", [])
        workflows: List[Dict[str, Any]] = []
        if isinstance(raw, list):
            for entry in raw:
                record = _clean_workflow_record(entry)
                if record is not None:
                    workflows.append(record)
        return {"version": 1, "workflows": workflows}, warnings

    def save_workflows(self, workflows: Any) -> None:
        """Persist the workflow list (cleaned). Raises StorageError."""
        stored: List[Dict[str, Any]] = []
        if isinstance(workflows, list):
            for entry in workflows:
                record = _clean_workflow_record(entry)
                if record is not None:
                    stored.append(record)
        _write_json(self._workflows_path(), {"version": 1, "workflows": stored})

    def _mutate_workflows(self, fn: Any) -> Any:
        """Read-modify-write the registry under one lock hold."""
        with path_lock(self._workflows_path()):
            data, _ = _read_json(self._workflows_path())
            raw = data.get("workflows", []) if isinstance(data, dict) else []
            workflows = [
                r for r in
                (_clean_workflow_record(e) for e in raw)
                if r is not None
            ] if isinstance(raw, list) else []
            result, updated = fn(workflows)
            _write_json(self._workflows_path(), {"version": 1, "workflows": updated})
            return result

    def create_workflow(
        self,
        name: Any,
        steps: Any,
        description: Any = "",
        known_tools: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Validate and store a pipeline; returns the stored record.

        Raises ValueError for invalid definitions or a full registry.
        """
        from services import workflows as workflows_svc
        from services.limits import MAX_WORKFLOWS_PER_USER

        clean_name, clean_desc, clean_steps = workflows_svc.validate_workflow(
            name, steps, description, known_tools
        )

        def _add(workflows: List[Dict[str, Any]]) -> Any:
            if len(workflows) >= MAX_WORKFLOWS_PER_USER:
                raise ValueError(
                    f"Workflow limit reached ({MAX_WORKFLOWS_PER_USER}). "
                    "Delete one first."
                )
            now = time.time()
            record: Dict[str, Any] = {
                "id": new_conversation_id(),
                "name": clean_name,
                "description": clean_desc,
                "steps": clean_steps,
                "created": now,
                "updated": now,
            }
            return dict(record), workflows + [record]

        return self._mutate_workflows(_add)

    def get_workflow(self, workflow_id: Any) -> Optional[Dict[str, Any]]:
        """Return a copy of one workflow, or None (unknown/malformed IDs)."""
        if not is_valid_id(workflow_id):
            return None
        data, _ = self.load_workflows()
        for entry in data["workflows"]:
            if entry["id"] == workflow_id:
                return dict(entry)
        return None

    def list_workflows(self) -> List[Dict[str, Any]]:
        """Workflows newest-first."""
        data, _ = self.load_workflows()
        matching = [dict(entry) for entry in data["workflows"]]
        matching.sort(key=lambda e: e.get("created", 0.0), reverse=True)
        return matching

    def update_workflow(
        self,
        workflow_id: Any,
        name: Any,
        steps: Any,
        description: Any = "",
        known_tools: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Full-replace a pipeline (re-validated); returns the record.

        The id/created survive; updated is bumped. Raises ValueError
        for unknown IDs or invalid definitions.
        """
        from services import workflows as workflows_svc

        if not is_valid_id(workflow_id):
            raise WorkflowNotFoundError("Workflow not found.")
        clean_name, clean_desc, clean_steps = workflows_svc.validate_workflow(
            name, steps, description, known_tools
        )

        def _replace(workflows: List[Dict[str, Any]]) -> Any:
            updated_list: List[Dict[str, Any]] = []
            found: Optional[Dict[str, Any]] = None
            for entry in workflows:
                if entry["id"] == workflow_id:
                    found = {
                        "id": entry["id"],
                        "name": clean_name,
                        "description": clean_desc,
                        "steps": clean_steps,
                        "created": entry.get("created", 0.0),
                        "updated": time.time(),
                    }
                    updated_list.append(found)
                else:
                    updated_list.append(entry)
            if found is None:
                raise WorkflowNotFoundError("Workflow not found.")
            return dict(found), updated_list

        return self._mutate_workflows(_replace)

    def delete_workflow(self, workflow_id: Any) -> bool:
        """Delete one workflow; False for unknown IDs."""
        if not is_valid_id(workflow_id):
            return False

        def _drop(workflows: List[Dict[str, Any]]) -> Any:
            kept = [e for e in workflows if e["id"] != workflow_id]
            return len(kept) != len(workflows), kept

        return bool(self._mutate_workflows(_drop))

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
