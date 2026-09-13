"""File creation + revision support: PDF, Markdown, legacy DOC + read_output.

Creation tools accept full content from the model and register an owned
downloadable artifact (immutable: revisions always create a NEW file,
originals are never overwritten). Every tool gates on the generation
quota BEFORE doing expensive work.

Revision flow (model-driven, no destructive ops):
  1. read_output(file_id) returns the prior artifact's editable source
     (the exact inputs it was built from, capped).
  2. The model applies the user's requested changes itself.
  3. The model calls the matching create_* tool with the FULL revised
     content, which registers a new version. The original is kept.

PDFs are written dependency-free (stdlib only) with built-in Helvetica/
Courier — no reportlab needed. Legacy .doc is Word-compatible HTML
(which Word/LibreOffice open natively for editing); the tool result
says so plainly instead of claiming native OLE bytes.
"""

import html as _html_mod
import io as _io
import re
import time
import uuid
from typing import Any, Dict, List, Tuple

from langchain_core.tools import tool

from services.context import get_current_user_id
from services.files import FileStore
from services.limits import MAX_DOCUMENT_CHARS, MAX_MAKE_BLOCKS
from services.obs import timed as obs_timed
from services.storage import StorageError, clean_generation_spec
from tools.gating import claim_generation_slot

# ---------------------------------------------------------------------------
# Shared lightweight-markdown blocks (same subset as build_document).


def _strip_inline(text: str) -> str:
    """Drop **bold**/*italic*/`code` markers for plain-text renderers."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*([^*\n]+?)\*", r"\1", text)
    return text.replace("`", "")


def _parse_blocks(markdown_text: str) -> List[Tuple[str, Any]]:
    """Parse lightweight markdown into (kind, payload) blocks.

    Kinds: h1/h2/h3, para, bullet, numbered, quote, code, table, pagebreak.
    """
    blocks: List[Tuple[str, Any]] = []
    lines = markdown_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i = 0
    in_code = False
    code_buf: List[str] = []
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_code:
                blocks.append(("code", "\n".join(code_buf)))
                code_buf = []
                in_code = False
            else:
                in_code = True
            i += 1
            continue
        if in_code:
            code_buf.append(line.rstrip())
            i += 1
            continue
        if not stripped:
            i += 1
            continue
        if stripped in ("---", "***", "___"):
            blocks.append(("pagebreak", None))
            i += 1
            continue
        if stripped.startswith("### "):
            blocks.append(("h3", stripped[4:].strip()))
        elif stripped.startswith("## "):
            blocks.append(("h2", stripped[3:].strip()))
        elif stripped.startswith("# "):
            blocks.append(("h1", stripped[2:].strip()))
        elif stripped.startswith("> "):
            quote_lines = [stripped[2:].strip()]
            i += 1
            while i < len(lines) and lines[i].strip().startswith("> "):
                quote_lines.append(lines[i].strip()[2:].strip())
                i += 1
            blocks.append(("quote", " ".join(quote_lines)))
            continue
        elif re.match(r"^[-*]\s+", stripped):
            items = [re.sub(r"^[-*]\s+", "", stripped).strip()]
            i += 1
            while i < len(lines) and re.match(r"^[-*]\s+", lines[i].strip()):
                items.append(re.sub(r"^[-*]\s+", "", lines[i].strip()).strip())
                i += 1
            blocks.append(("bullet", [x for x in items if x]))
            continue
        elif re.match(r"^\d+[.)]\s+", stripped):
            items = [re.sub(r"^\d+[.)]\s+", "", stripped).strip()]
            i += 1
            while i < len(lines) and re.match(r"^\d+[.)]\s+", lines[i].strip()):
                items.append(re.sub(r"^\d+[.)]\s+", "", lines[i].strip()).strip())
                i += 1
            blocks.append(("numbered", [x for x in items if x]))
            continue
        elif "|" in stripped:
            rows = [stripped]
            i += 1
            while i < len(lines) and "|" in lines[i]:
                rows.append(lines[i].strip())
                i += 1
            parsed = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
            parsed = [r for r in parsed if any(c for c in r)]
            parsed = [r for r in parsed if not all(re.fullmatch(r":?-{1,}:?", c or "") for c in r)]
            if 1 <= len(parsed[0]) <= 6:
                blocks.append(("table", parsed))
            else:
                for r in parsed:
                    blocks.append(("para", " | ".join(r)))
            continue
        else:
            para_lines = [stripped]
            i += 1
            while i < len(lines) and lines[i].strip() and not re.match(
                r"^(#{1,3}\s|>\s|[-*]\s|\d+[.)]\s|```|---$|\*\*\*$|___$)", lines[i].strip()
            ) and "|" not in lines[i]:
                para_lines.append(lines[i].strip())
                i += 1
            blocks.append(("para", " ".join(para_lines)))
            continue
        i += 1
    if in_code and code_buf:
        blocks.append(("code", "\n".join(code_buf)))
    return blocks[:MAX_MAKE_BLOCKS]


_SUBSTANTIVE = frozenset({"para", "bullet", "numbered", "table", "code", "quote", "h2", "h3"})


def _has_substance(blocks: List[Tuple[str, Any]]) -> bool:
    return any(kind in _SUBSTANTIVE for kind, _ in blocks)


# ---------------------------------------------------------------------------
# Stdlib PDF writer (built-in fonts only: Helvetica family + Courier).

_PDF_WINANSI_MAP = {
    "\u2014": "--", "\u2013": "-", "\u2018": "'",
    "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2022": "-", "\u2026": "...", "\u00a0": " ",
    "\u2192": "->", "\u00d7": "x", "\u2713": "v",
}

_PDF_PAGE_W = 595.0
_PDF_PAGE_H = 842.0
_PDF_MARGIN = 72.0
_PDF_TEXT_W = _PDF_PAGE_W - 2 * _PDF_MARGIN
_PDF_TOP = _PDF_PAGE_H - _PDF_MARGIN
_PDF_BOTTOM = _PDF_MARGIN + 12.0

# font_key -> (pdf_basefont, avg char width as fraction of size)
_PDF_FONTS: Dict[str, Tuple[str, str, float]] = {
    "body": ("F1", "Helvetica", 0.50),
    "bold": ("F2", "Helvetica-Bold", 0.55),
    "italic": ("F3", "Helvetica-Oblique", 0.50),
    "code": ("F4", "Courier", 0.60),
}


def _pdf_clean(text: str) -> str:
    for src, dst in _PDF_WINANSI_MAP.items():
        text = text.replace(src, dst)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _pdf_wrap(text: str, font_key: str, size: float, indent: float = 0.0) -> List[str]:
    """Greedy word-wrap to the text width (never raises, never empty)."""
    factor = _PDF_FONTS[font_key][2]
    usable = max(80.0, _PDF_TEXT_W - indent)
    max_chars = max(10, int(usable / (size * factor)))
    words = str(text or "").split()
    if not words:
        return [""]
    lines: List[str] = []
    current: List[str] = []
    current_len = 0
    for word in words:
        while len(word) > max_chars:
            # Hard-split pathological long tokens (URLs, code).
            if current:
                lines.append(" ".join(current))
                current, current_len = [], 0
            lines.append(word[:max_chars])
            word = word[max_chars:]
        extra = len(word) + (1 if current else 0)
        if current_len + extra > max_chars and current:
            lines.append(" ".join(current))
            current, current_len = [word], len(word)
        else:
            current.append(word)
            current_len += extra
    if current:
        lines.append(" ".join(current))
    return lines or [""]


def _blocks_to_pdf_lines(title: str, blocks: List[Tuple[str, Any]]) -> List[Tuple[str, float, float, str]]:
    """Flatten blocks to (font_key, size, indent, text) drawable lines."""
    out: List[Tuple[str, float, float, str]] = []
    if title and title.strip():
        for line in _pdf_wrap(_strip_inline(title.strip()), "bold", 22.0):
            out.append(("bold", 22.0, 0.0, line))
        out.append(("body", 11.0, 0.0, ""))
    for kind, payload in blocks:
        if kind == "pagebreak":
            out.append(("__break__", 0.0, 0.0, ""))
        elif kind in ("h1", "h2", "h3"):
            size = {"h1": 17.0, "h2": 14.0, "h3": 12.0}[kind]
            out.append(("body", 11.0, 0.0, ""))
            for line in _pdf_wrap(_strip_inline(str(payload)), "bold", size):
                out.append(("bold", size, 0.0, line))
        elif kind == "para":
            for line in _pdf_wrap(_strip_inline(str(payload)), "body", 11.0):
                out.append(("body", 11.0, 0.0, line))
            out.append(("body", 11.0, 0.0, ""))
        elif kind == "bullet":
            for item in payload[:50]:
                for n, line in enumerate(_pdf_wrap(_strip_inline(str(item)), "body", 11.0, indent=18.0)):
                    out.append(("body", 11.0, 18.0, ("- " if n == 0 else "  ") + line))
            out.append(("body", 11.0, 0.0, ""))
        elif kind == "numbered":
            for num, item in enumerate(payload[:50], start=1):
                prefix = f"{num}. "
                for n, line in enumerate(_pdf_wrap(_strip_inline(str(item)), "body", 11.0, indent=18.0)):
                    out.append(("body", 11.0, 18.0, (prefix if n == 0 else " " * len(prefix)) + line))
            out.append(("body", 11.0, 0.0, ""))
        elif kind == "quote":
            for line in _pdf_wrap(_strip_inline(str(payload)), "italic", 11.0, indent=18.0):
                out.append(("italic", 11.0, 18.0, line))
            out.append(("body", 11.0, 0.0, ""))
        elif kind == "code":
            for raw_line in str(payload).split("\n")[:100]:
                line = raw_line.strip()
                if not line:
                    continue
                if len(line) > 90:
                    for chunk in _pdf_wrap(line, "code", 9.5, indent=18.0):
                        out.append(("code", 9.5, 18.0, chunk))
                else:
                    out.append(("code", 9.5, 18.0, line))
            out.append(("body", 11.0, 0.0, ""))
        elif kind == "table":
            headers = payload[0]
            out.append(("bold", 10.0, 0.0, " | ".join(str(h) for h in headers)[:150]))
            for row in payload[1:13]:
                line = " | ".join(str(c) for c in row[:6])[:150]
                out.append(("body", 10.0, 0.0, line))
            out.append(("body", 11.0, 0.0, ""))
    return out


def _build_pdf(title: str, blocks: List[Tuple[str, Any]]) -> bytes:
    """Serialize drawable lines to a minimal multi-page PDF (A4)."""
    draw = _blocks_to_pdf_lines(title, blocks)
    pages: List[List[Tuple[str, float, float, str]]] = [[]]
    for op in draw:
        if op[0] == "__break__":
            pages.append([])
            continue
        _, size, _, _ = op
        leading = max(12.0, size * 1.35)
        # Estimate current page height.
        used = sum(max(12.0, s * 1.35) for _, s, _, _ in pages[-1])
        if pages[-1] and used + leading > (_PDF_TOP - _PDF_BOTTOM):
            pages.append([])
        pages[-1].append(op)
    pages = [p for p in pages if p] or [[("body", 11.0, 0.0, " ")]]

    font_names = ["F1", "F2", "F3", "F4"]
    basefonts = ["Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Courier"]
    n_pages = len(pages)
    # Object numbering: 1 catalog, 2 pages, then per page (page, content),
    # then 4 fonts at the end.
    page_obj_nums: List[int] = []
    content_obj_nums: List[int] = []
    num = 3
    for _ in pages:
        page_obj_nums.append(num)
        content_obj_nums.append(num + 1)
        num += 2
    font_obj_nums = [num, num + 1, num + 2, num + 3]

    objects: Dict[int, bytes] = {}
    kids = " ".join(f"{n} 0 R" for n in page_obj_nums)
    objects[1] = f"<< /Type /Catalog /Pages 2 0 R >>".encode("latin-1")
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode("latin-1")
    for fnum, base in zip(font_obj_nums, basefonts):
        objects[fnum] = (f"<< /Type /Font /Subtype /Type1 /BaseFont /{base} >>").encode("latin-1")

    for idx, (pnum, cnum) in enumerate(zip(page_obj_nums, content_obj_nums)):
        # One text object per indent/size/font run (Td only moves
        # relatively, so absolute moves handle indent changes cleanly).
        rebuilt: List[str] = ["BT"]
        y = _PDF_TOP
        first_line = True
        last_indent: float = -1.0
        last_size: float = -1.0
        last_font: str = ""
        for font_key, size, indent, text in pages[idx]:
            leading = max(12.0, size * 1.35)
            y -= leading
            cleaned = _pdf_escape(_pdf_clean(text))[:1000]
            fname = _PDF_FONTS[font_key][0]
            x = _PDF_MARGIN + indent
            if first_line:
                rebuilt.append(
                    f"/{fname} {size:.1f} Tf {x:.1f} {y:.1f} Td ({cleaned}) Tj")
                first_line = False
            elif abs(indent - last_indent) > 0.01 or abs(size - last_size) > 0.01 or fname != last_font:
                rebuilt.append("ET")
                rebuilt.append("BT")
                rebuilt.append(
                    f"/{fname} {size:.1f} Tf {x:.1f} {y:.1f} Td ({cleaned}) Tj")
            else:
                rebuilt.append(f"0 {-leading:.1f} Td ({cleaned}) Tj")
            last_indent, last_size, last_font = indent, size, fname
        rebuilt.append("ET")
        # Footer with page number.
        rebuilt.append(
            f"BT /F1 9 Tf 270.0 40.0 Td (Page {idx + 1} of {n_pages}) Tj ET")
        stream = "\n".join(rebuilt).encode("latin-1")
        objects[cnum] = (f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1")
                         + stream + b"\nendstream")
        fontres = " ".join(f"/{fn} {fnum} 0 R" for fn, fnum in zip(font_names, font_obj_nums))
        objects[pnum] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {_PDF_PAGE_W:.0f} {_PDF_PAGE_H:.0f}] "
            f"/Resources << /Font << {fontres} >> >> /Contents {cnum} 0 R >>"
        ).encode("latin-1")

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: Dict[int, int] = {}
    for obj_num in sorted(objects):
        offsets[obj_num] = len(out)
        out += f"{obj_num} 0 obj\n".encode("latin-1") + objects[obj_num] + b"\nendobj\n"
    xref_at = len(out)
    total = max(offsets) + 1
    out += f"xref\n0 {total}\n".encode("latin-1")
    out += b"0000000000 65535 f \n"
    for obj_num in range(1, total):
        out += f"{offsets.get(obj_num, 0):010d} 00000 n \n".encode("latin-1")
    out += (f"trailer\n<< /Size {total} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n").encode("latin-1")
    return bytes(out)


# ---------------------------------------------------------------------------
# Word-compatible .doc (HTML payload Word/LibreOffice open for editing).

def _blocks_to_word_html(title: str, blocks: List[Tuple[str, Any]]) -> str:
    parts: List[str] = [
        '<html xmlns:o="urn:schemas-microsoft-com:office:office" '
        'xmlns:w="urn:schemas-microsoft-com:office:word" '
        'xmlns="http://www.w3.org/TR/REC-html40">',
        "<head>",
        '<meta http-equiv="Content-Type" content="text/html; charset=utf-8">',
        '<meta name="ProgId" content="Word.Document">',
        f"<title>{_html_mod.escape(title[:120])}</title>",
        "<style>p{font-family:Calibri,Arial;font-size:11pt} "
        "h1{font-size:18pt} h2{font-size:15pt} h3{font-size:12pt} "
        "table{border-collapse:collapse} td,th{border:1px solid #999;padding:4px}</style>",
        "</head>",
        "<body>",
        f"<h1>{_html_mod.escape(title[:120])}</h1>",
    ]
    esc = _html_mod.escape
    for kind, payload in blocks:
        if kind == "pagebreak":
            parts.append('<br clear="all" style="page-break-before:always">')
        elif kind in ("h1", "h2", "h3"):
            tag = {"h1": "h2", "h2": "h2", "h3": "h3"}[kind]
            parts.append(f"<{tag}>{esc(_strip_inline(str(payload))[:500])}</{tag}>")
        elif kind == "para":
            parts.append(f"<p>{esc(_strip_inline(str(payload))[:3000])}</p>")
        elif kind == "bullet":
            parts.append("<ul>")
            for item in payload[:50]:
                parts.append(f"<li>{esc(_strip_inline(str(item))[:1000])}</li>")
            parts.append("</ul>")
        elif kind == "numbered":
            parts.append("<ol>")
            for item in payload[:50]:
                parts.append(f"<li>{esc(_strip_inline(str(item))[:1000])}</li>")
            parts.append("</ol>")
        elif kind == "quote":
            parts.append(f"<blockquote><p><i>{esc(_strip_inline(str(payload))[:2000])}</i></p></blockquote>")
        elif kind == "code":
            parts.append(f"<pre>{esc(str(payload)[:4000])}</pre>")
        elif kind == "table":
            headers = payload[0]
            parts.append("<table><tr>")
            for header in headers:
                parts.append(f"<th><b>{esc(str(header)[:200])}</b></th>")
            parts.append("</tr>")
            for row in payload[1:13]:
                parts.append("<tr>")
                for j in range(len(headers)):
                    cell = str(row[j] if j < len(row) else "")[:200]
                    parts.append(f"<td>{esc(cell)}</td>")
                parts.append("</tr>")
            parts.append("</table>")
    parts.append("</body></html>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Creation tools.


@tool
def create_pdf(title: str, markdown_text: str) -> str:
    """Create a PDF document (.pdf file) from lightweight markdown.

    Use ONLY when the user explicitly asks for a PDF. Supported input:
    # / ## / ### headings, paragraphs, - bullets, 1. numbered lists,
    > quotes, ``` code blocks, | tables |, --- page breaks.

    Args:
        title: Document title (first-page heading).
        markdown_text: The document body in lightweight markdown.

    Returns:
        Summary with filename (plus download ID) and page count,
        or a STATUS= error marker.
    """
    if not markdown_text or not markdown_text.strip():
        return "STATUS=INVALID tool=create_pdf: empty document text."
    if not title or not title.strip():
        return "STATUS=INVALID tool=create_pdf: empty title."
    user_id, denied = claim_generation_slot("create_pdf")
    if denied is not None:
        return denied
    try:
        blocks = _parse_blocks(markdown_text)
        if not _has_substance(blocks):
            return "STATUS=INVALID tool=create_pdf: no substantive content found."
        data = _build_pdf(title.strip()[:120], blocks)
        # Quality control: reopen and verify pages + extractable text.
        try:
            from pypdf import PdfReader

            check = PdfReader(_io.BytesIO(data))
            if not check.pages:
                return "STATUS=FAILED tool=create_pdf: validation failed (no pages)."
        except Exception as e:
            return f"STATUS=FAILED tool=create_pdf: output unreadable ({str(e)[:120]})."
        filename: str = f"pdf_{uuid.uuid4().hex[:8]}.pdf"
        try:
            spec = {"kind": "pdf", "tool": "create_pdf",
                    "input": {"title": title, "markdown_text": markdown_text},
                    "created": time.time()}
            meta = FileStore(user_id).register_output(filename, data, "pdf", spec)
            return (f"PDF saved as {meta.display_name} "
                    f"({len(check.pages)} page(s), file ID: {meta.id})")
        except StorageError as e:
            return f"STATUS=FAILED tool=create_pdf: {e}"
    except Exception as e:
        return f"STATUS=FAILED tool=create_pdf: {str(e)[:200]}"


@tool
def create_markdown(title: str, markdown_text: str) -> str:
    """Create a Markdown file (.md) saved as a downloadable artifact.

    Use ONLY when the user explicitly asks for a markdown file, .md
    export, or notes file. Do NOT use for plain chat answers — reply
    in chat text instead.

    Args:
        title: File title (becomes the top # heading + filename basis).
        markdown_text: Full markdown body.

    Returns:
        Summary with filename (plus download ID), or a STATUS= error.
    """
    if not markdown_text or not markdown_text.strip():
        return "STATUS=INVALID tool=create_markdown: empty document text."
    if not title or not title.strip():
        return "STATUS=INVALID tool=create_markdown: empty title."
    user_id, denied = claim_generation_slot("create_markdown")
    if denied is not None:
        return denied
    try:
        body = markdown_text.strip()
        if not body.startswith("#"):
            body = f"# {title.strip()[:120]}\n\n{body}"
        data = body.encode("utf-8")
        filename: str = f"md_{uuid.uuid4().hex[:8]}.md"
        try:
            spec = {"kind": "md", "tool": "create_markdown",
                    "input": {"title": title, "markdown_text": markdown_text},
                    "created": time.time()}
            meta = FileStore(user_id).register_output(filename, data, "md", spec)
            return f"Markdown saved as {meta.display_name} (file ID: {meta.id})"
        except StorageError as e:
            return f"STATUS=FAILED tool=create_markdown: {e}"
    except Exception as e:
        return f"STATUS=FAILED tool=create_markdown: {str(e)[:200]}"


@tool
def create_doc(title: str, markdown_text: str) -> str:
    """Create a Word 97-2003 compatible document (.doc file).

    Use ONLY when the user explicitly asks for a .doc file. For modern
    Word files prefer build_document (.docx). The .doc is Word-compatible
    HTML, which Word and LibreOffice open natively for editing (pure
    Python — no OLE writer needed).

    Args:
        title: Document title (top heading).
        markdown_text: Body in lightweight markdown (# headings,
            paragraphs, - bullets, 1. lists, > quotes, ``` code,
            | tables |, --- page breaks).

    Returns:
        Summary with filename (plus download ID), or a STATUS= error.
    """
    if not markdown_text or not markdown_text.strip():
        return "STATUS=INVALID tool=create_doc: empty document text."
    if not title or not title.strip():
        return "STATUS=INVALID tool=create_doc: empty title."
    user_id, denied = claim_generation_slot("create_doc")
    if denied is not None:
        return denied
    try:
        blocks = _parse_blocks(markdown_text)
        if not _has_substance(blocks):
            return "STATUS=INVALID tool=create_doc: no substantive content found."
        payload = _blocks_to_word_html(title.strip()[:120], blocks)
        data = payload.encode("utf-8")
        filename: str = f"doc_{uuid.uuid4().hex[:8]}.doc"
        try:
            spec = {"kind": "doc", "tool": "create_doc",
                    "input": {"title": title, "markdown_text": markdown_text},
                    "created": time.time()}
            meta = FileStore(user_id).register_output(filename, data, "doc", spec)
            return (f"Document saved as {meta.display_name} (file ID: {meta.id}) "
                    "[Word 97-2003 compatible — opens directly in Word/LibreOffice.]")
        except StorageError as e:
            return f"STATUS=FAILED tool=create_doc: {e}"
    except Exception as e:
        return f"STATUS=FAILED tool=create_doc: {str(e)[:200]}"


_READ_OUTPUT_FIELD_CAP = 20000


@tool
def read_output(file_id: str) -> str:
    """Read back a generated file's editable source for revision.

    Use when the user says "edit it", "revise", or "update the file":
    1. Call this with the artifact's file ID to get the exact source
       it was built from (title/content/markdown/spec, capped).
    2. Apply the user's requested changes YOURSELF to that source.
    3. Call the matching create_* tool with the FULL revised content.
       That registers a NEW version — the original is always kept,
       never overwritten.

    Args:
        file_id: The file ID of an artifact owned by the user.

    Returns:
        Kind, name, originating tool, and editable source fields,
        or a STATUS= error marker.
    """
    try:
        with obs_timed("output.read") as rec:
            user_id = get_current_user_id()
            if not user_id:
                return "STATUS=INVALID tool=read_output: no user context."
            store = FileStore(user_id)
            meta = store.get_output(file_id)
            if meta is None:
                rec["status"] = "denied"
                return ("STATUS=DENIED tool=read_output: unknown file ID "
                        "or not owned by you.")
            kind = str(getattr(meta, "kind", "file") or "file")
            name = str(getattr(meta, "display_name", "file") or "file")
            spec = clean_generation_spec(getattr(meta, "spec", None))
            if spec is None:
                rec["status"] = "failed"
                return (
                    f"STATUS=INVALID tool=read_output: '{name}' ({kind}) has "
                    "no editable source (built before specs or unsupported). "
                    "Ask the user for the full replacement content, then call "
                    "the matching create_* tool to save a new version."
                )
            tool_name = str(spec.get("tool", ""))
            raw_input = spec.get("input", {})
            if not isinstance(raw_input, dict):
                raw_input = {}
            lines = [f"File: '{name}' ({kind}), built by {tool_name}."]
            for key in sorted(raw_input):
                value = raw_input.get(key, "")
                value = value if isinstance(value, str) else str(value)
                note = ""
                if len(value) > _READ_OUTPUT_FIELD_CAP:
                    value = value[:_READ_OUTPUT_FIELD_CAP]
                    note = " [truncated]"
                lines.append(f"--- {key}{note} ---")
                lines.append(value)
            lines.append("To revise: edit the source above yourself, then call "
                         f"{tool_name} with the FULL revised content (new version; "
                         "the original is kept).")
            text = "\n".join(lines)
            if len(text) > MAX_DOCUMENT_CHARS:
                text = text[:MAX_DOCUMENT_CHARS] + "\n[Note: source truncated due to length.]"
            return text
    except Exception as e:
        return f"STATUS=FAILED tool=read_output: {str(e)[:200]}"
