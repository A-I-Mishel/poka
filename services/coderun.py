"""Real code execution inside the user's workspace (private-mode only).

Threat model: the caller is the trusted owner (private mode gate lives
at the tool layer), but the CODE often comes from the model and may be
steered by prompt-injected tool output. This runner therefore:
- locks cwd to the user's workspace (no repo/host paths),
- never uses shell=True (fixed argv per language, no injection),
- strips secret-like env vars, caps time/output/args,
- runs one file at a time with a per-call timeout.

This is OS-process isolation, NOT a kernel/container boundary: a
malicious snippet can still burn CPU, fill the workspace quota, or
exfiltrate over the network. Hosts needing hard isolation must
containerize the API process. Public (open-mode) deploys must keep
this tool denied — the tool gate enforces that.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

from services.limits import (
    MAX_CODE_ARGS_CHARS,
    MAX_CODE_EXEC_SECONDS,
    MAX_CODE_FILE_CHARS,
    MAX_CODE_OUTPUT_CHARS,
)
from services.storage import StorageError
from services.workspace import (
    WORKSPACE_ALLOWED_EXTS,
    clean_relpath,
    resolve_in_workspace,
    workspace_root,
    write_workspace_file,
)

_LANG_BY_EXT: Dict[str, str] = {
    "py": "python", "pyi": "python",
    "js": "node", "mjs": "node", "cjs": "node", "jsx": "node",
    "ts": "node", "mts": "node", "tsx": "node",
    "java": "java", "go": "go",
    "c": "c", "h": "c", "cpp": "cpp", "hpp": "cpp", "cc": "cpp",
    "rs": "rust", "php": "php", "rb": "ruby",
}

_RUNNABLE_EXTS = frozenset({
    "py", "js", "mjs", "cjs", "ts", "mts",
    "java", "go", "c", "cpp", "cc", "rs", "php", "rb",
})

def _safe_env() -> Dict[str, str]:
    """Minimal env for child processes (delegates to services.env)."""
    from services.env import safe_env as _shared_safe_env

    return _shared_safe_env()


def _which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


def detect_language(relpath: str, hint: str = "") -> str:
    """Return canonical language for a file, honoring an explicit hint."""
    h = str(hint or "").strip().lower()
    aliases = {"py": "python", "python": "python", "js": "node",
               "node": "node", "javascript": "node", "ts": "node",
               "typescript": "node", "java": "java", "go": "go",
               "c": "c", "cpp": "cpp", "c++": "cpp", "rs": "rust",
               "rust": "rust", "php": "php", "rb": "ruby", "ruby": "ruby"}
    if h and h in aliases:
        return aliases[h]
    ext = relpath.rsplit(".", 1)[-1].lower() if "." in relpath else ""
    return _LANG_BY_EXT.get(ext, "")


def _build_command(lang: str, path: Path) -> Optional[List[str]]:
    """Fixed argv for one language. None when toolchain is missing."""
    if lang == "python":
        return [sys.executable, str(path)]
    if lang == "node":
        node = _which("node")
        if not node:
            return None
        return [node, str(path)]
    if lang == "java":
        java = _which("java")
        if not java:
            return None
        # Single-file launch (Java 11+): `java File.java args...`
        return [java, str(path)]
    if lang == "go":
        go = _which("go")
        if not go:
            return None
        return [go, "run", str(path)]
    if lang in ("c", "cpp"):
        comp = _which("gcc" if lang == "c" else "g++")
        if not comp:
            return None
        return [comp]  # compile step handled by caller (needs exe path)
    if lang == "rust":
        rustc = _which("rustc")
        if not rustc:
            return None
        return [rustc]
    if lang == "php":
        php = _which("php")
        if not php:
            return None
        return [php, str(path)]
    if lang == "ruby":
        ruby = _which("ruby")
        if not ruby:
            return None
        return [ruby, str(path)]
    return None


def _run_argv(argv: List[str], cwd: Path, extra_args: List[str]) -> Dict[str, object]:
    full = list(argv) + list(extra_args)
    started = time.time()
    try:
        proc = subprocess.run(  # noqa: S603 (fixed allowlisted argv, shell=False, secret-stripped env)
            full, cwd=str(cwd), env=_safe_env(),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=MAX_CODE_EXEC_SECONDS, shell=False, text=True,
            errors="replace",
        )
        out = proc.stdout or ""
        truncated = False
        if len(out) > MAX_CODE_OUTPUT_CHARS:
            out = out[:MAX_CODE_OUTPUT_CHARS]
            truncated = True
        return {"output": out, "exit_code": int(proc.returncode),
                "truncated": truncated,
                "duration_s": round(time.time() - started, 2)}
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") if isinstance(e.stdout, str) else ""
        if len(out) > MAX_CODE_OUTPUT_CHARS:
            out = out[:MAX_CODE_OUTPUT_CHARS]
        return {"error": f"timed out after {MAX_CODE_EXEC_SECONDS:g}s",
                "output": out, "timeout": True}
    except OSError as e:
        return {"error": f"could not start runtime ({e})"}


def execute_file(user_id: str, relpath: str, args: str = "") -> Dict[str, object]:
    """Run one workspace file. Returns output/exit_code or error dict."""
    cleaned = clean_relpath(relpath)
    ext = cleaned.rsplit(".", 1)[-1].lower() if "." in cleaned else ""
    if ext not in _RUNNABLE_EXTS:
        return {"error": f".{ext or '?'} files cannot be executed "
                "(runnable: py, js/mjs/cjs, ts/mts, java, go, c, cpp, rs, php, rb).",
                "invalid": True}
    path = resolve_in_workspace(user_id, cleaned)
    if not path.is_file():
        return {"error": f"workspace file not found: {cleaned}", "invalid": True}
    try:
        if path.stat().st_size > 1_048_576:
            return {"error": "file too large to execute (limit 1 MiB).",
                    "invalid": True}
    except OSError as e:
        return {"error": f"cannot stat file ({e})"}
    arg_text = str(args or "")
    if len(arg_text) > MAX_CODE_ARGS_CHARS:
        return {"error": f"args too long (limit {MAX_CODE_ARGS_CHARS} chars).",
                "invalid": True}
    extra = arg_text.strip().split() if arg_text.strip() else []
    if len(extra) > 20:
        return {"error": "too many args (max 20).", "invalid": True}
    lang = detect_language(cleaned)
    if not lang:
        return {"error": f"cannot detect language for {cleaned}.", "invalid": True}
    root = workspace_root(user_id, create=True)

    # Compiled languages: compile to workspace/.run/<name>.exe then run.
    if lang in ("c", "cpp", "rust"):
        return _compile_and_run(user_id, lang, path, root, extra)
    argv = _build_command(lang, path)
    if argv is None:
        return {"error": f"{lang} runtime not installed on this host."}
    return _run_argv(argv, root, extra)


def _compile_and_run(user_id: str, lang: str, src: Path,
                     root: Path, extra: List[str]) -> Dict[str, object]:
    rundir = root / ".run"
    try:
        rundir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return {"error": f"cannot prepare run dir ({e})"}
    exe = rundir / (src.stem + "_" + lang + (".exe" if os.name == "nt" else ".out"))
    if lang in ("c", "cpp"):
        comp = _which("gcc" if lang == "c" else "g++")
        if comp is None:
            return {"error": f"{lang} compiler not installed on this host."}
        comp_argv = [comp, str(src), "-O2", "-o", str(exe)]
        res = _run_argv(comp_argv, root, [])
        if "error" in res:
            return {"error": f"compile {res.get('error')}: {(res.get('output') or '')[:2000]}"}
        try:
            code = int(res.get("exit_code", 1))
        except (TypeError, ValueError):
            code = 1
        if code != 0:
            return {"error": f"compile failed:\n{(res.get('output') or '')[:4000]}"}
    else:  # rust
        rustc = _which("rustc")
        if rustc is None:
            return {"error": "rust compiler not installed on this host."}
        res = _run_argv([rustc, str(src), "-O", "-o", str(exe)], root, [])
        if "error" in res:
            return {"error": f"compile {res.get('error')}: {(res.get('output') or '')[:2000]}"}
        if int(res.get("exit_code", 1)) != 0:
            return {"error": f"compile failed:\n{(res.get('output') or '')[:4000]}"}
    return _run_argv([str(exe)], root, extra)


def execute_inline(user_id: str, language: str, code: str) -> Dict[str, object]:
    """Write an inline snippet to workspace/_snippet.<ext> and run it."""
    lang = detect_language("x." + str(language or "").strip().lower(), str(language or ""))
    if not lang:
        # Try treating `language` as an extension directly.
        lang = detect_language(f"snippet.{language}", "")
    if not lang:
        return {"error": "unknown language (try: python, node/js/ts, java, go, c, cpp, rust, php, ruby).",
                "invalid": True}
    ext_map = {"python": "py", "node": "mjs", "java": "java", "go": "go",
               "c": "c", "cpp": "cpp", "rust": "rs", "php": "php", "ruby": "rb"}
    ext = ext_map.get(lang, "")
    if not ext:
        return {"error": f"language {lang} is not runnable.", "invalid": True}
    text = str(code or "")
    if not text.strip():
        return {"error": "no code provided.", "invalid": True}
    if len(text) > MAX_CODE_FILE_CHARS:
        return {"error": f"code too large ({len(text)} chars, limit {MAX_CODE_FILE_CHARS}).",
                "invalid": True}
    if ext not in WORKSPACE_ALLOWED_EXTS:
        return {"error": f".{ext} snippets are not supported.", "invalid": True}
    # Java single-file launch needs a matching class name when public;
    # keep the snippet class non-public so _snippet.java always runs.
    if lang == "java" and "class" not in text:
        text = "class Snippet {\n    public static void main(String[] a) {\n" \
               + text + "\n    }\n}\n"
    rel = f"_snippet.{ext}"
    try:
        write_workspace_file(user_id, rel, text)
    except StorageError as e:
        return {"error": str(e), "invalid": True}
    return execute_file(user_id, rel)
