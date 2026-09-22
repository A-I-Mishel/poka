"""Document reading: text/code/html/zip/legacy + docx/pptx/xlsx by upload ID.

File tools accept opaque upload IDs only — never filesystem paths.
Results carry STATUS= markers so failures can't be mistaken for data.
Text output is capped (MAX_DOCUMENT_CHARS) with truncation notes.
Legacy (.doc/.ppt/.xls/.rtf) and archive (.zip) extraction is
best-effort stdlib-only and carries a fidelity note — never silently
presented as exact.
"""

import html as _html
import logging
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Tuple

from langchain_core.tools import tool

from services.context import get_current_user_id
from services.files import FileStore
from services.limits import (
    MAX_DOCUMENT_CHARS,
    MAX_UPLOAD_BYTES,
    MAX_ZIP_FILE_BYTES,
    MAX_ZIP_FILES,
    MAX_ZIP_LISTED,
    MAX_ZIP_UNCOMPRESSED_BYTES,
)
from services.obs import timed as obs_timed
from tools.parse_cache import ParseCache

logger = logging.getLogger(__name__)

# ponytail: mtime-keyed text cache — second read in same chat is RAM, not re-parse
_DOC_CACHE = ParseCache(32)

_TEXT_EXTS = frozenset({
    "txt", "md", "markdown", "log", "json", "tsv",
    "xml", "svg",
    "yaml", "yml", "toml", "ini", "cfg", "conf",
    "css", "scss", "less",
    "js", "mjs", "cjs", "jsx", "ts", "mts", "tsx",
    "py", "pyi", "java", "c", "h", "cpp", "hpp", "cc",
    "cs", "go", "rs", "php", "rb", "swift", "kt", "kts",
    "scala", "pl", "lua", "sh", "bash", "zsh", "bat", "cmd",
    "ps1", "sql", "r", "jl", "vue", "svelte",
})

_HTML_EXTS = frozenset({"html", "htm", "xhtml", "shtml"})


class _HtmlTextExtractor(HTMLParser):
    """Stdlib-only HTML → text. Drops scripts/styles, keeps block breaks."""

    _BLOCK_TAGS = frozenset({
        "p", "div", "section", "article", "header", "footer", "main",
        "h1", "h2", "h3", "h4", "h5", "h6", "li", "ul", "ol",
        "tr", "table", "br", "hr", "blockquote", "pre",
    })
    _SKIP_TAGS = frozenset({"script", "style", "noscript", "template"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        name = str(tag or "").lower()
        if name in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if name in self._BLOCK_TAGS:
            self._parts.append("\n")
        if name == "a":
            for key, value in (attrs or []):
                if str(key).lower() == "href" and value:
                    self._pending_href = str(value)[:500]
                    break
            else:
                self._pending_href = ""
        else:
            self._pending_href = ""

    def handle_endtag(self, tag: str) -> None:
        name = str(tag or "").lower()
        if name in self._SKIP_TAGS:
            if self._skip_depth > 0:
                self._skip_depth -= 1
            return
        if name in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if data:
            self._parts.append(data)

    def get_text(self) -> str:
        raw = "".join(self._parts)
        text = _html.unescape(raw)
        lines = [line.strip() for line in text.splitlines()]
        lines = [" ".join(line.split()) for line in lines]
        return "\n".join(line for line in lines if line)


def _resolve_document(upload_id: str):
    """Resolve upload ID to (path, ext, None) or (None, '', STATUS=...)."""
    user_id = get_current_user_id()
    if not user_id:
        return None, "", "STATUS=DENIED tool=read_document: no user context, cannot resolve uploads."
    meta = FileStore(user_id).get_upload(upload_id)
    if meta is None:
        return None, "", "STATUS=DENIED tool=read_document: unknown upload ID or not owned by you."
    path = FileStore(user_id).resolve_upload(upload_id)
    if path is None:
        return None, "", "STATUS=DENIED tool=read_document: upload file is unavailable."
    try:
        if path.stat().st_size > MAX_UPLOAD_BYTES:
            return None, "", "STATUS=DENIED tool=read_document: upload exceeds the size limit."
    except OSError as e:
        return None, "", f"STATUS=FAILED tool=read_document: cannot stat upload ({e})."
    return path, str(getattr(meta, "ext", "") or "").lower(), None


def _read_text_file(path) -> str:
    raw = path.read_bytes()
    if b"\x00" in raw[:8192]:
        raise ValueError("binary file, not a text document")
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _read_html_file(path) -> str:
    raw = path.read_bytes()
    if b"\x00" in raw[:8192]:
        raise ValueError("binary file, not an HTML document")
    text_html = ""
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text_html = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text_html = raw.decode("utf-8", errors="replace")
    parser = _HtmlTextExtractor()
    try:
        parser.feed(text_html[:500000])
        parser.close()
    except Exception as e:
        raise ValueError(f"cannot parse html ({e})")
    return parser.get_text()


def _decode_inner_text(blob: bytes, name: str) -> str:
    """Decode one zip member as text or stripped HTML (never raises)."""
    if b"\x00" in blob[:8192]:
        raise ValueError("binary member")
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            decoded = blob.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        decoded = blob.decode("utf-8", errors="replace")
    if ext in _HTML_EXTS:
        parser = _HtmlTextExtractor()
        parser.feed(decoded[:500000])
        parser.close()
        return parser.get_text()
    return decoded


def _safe_zip_members(z: zipfile.ZipFile):
    """Yield (ZipInfo, safe_name) skipping dirs/absolute/traversal entries."""
    for info in z.infolist():
        raw = (info.filename or "").replace("\\", "/").strip()
        if not raw or raw.endswith("/"):
            continue
        try:
            if info.is_dir():
                continue
        except Exception:
            logger.debug("zip is_dir check failed; treating as file", exc_info=True)
        if raw.startswith("/") or raw.startswith("~"):
            continue
        parts = [p for p in raw.split("/") if p not in ("", ".")]
        if not parts or any(p == ".." for p in parts):
            continue
        yield info, "/".join(parts)


def _read_zip_file(path) -> str:
    try:
        z = zipfile.ZipFile(str(path))
    except Exception as e:
        raise ValueError(f"cannot open zip ({e})")
    with z:
        try:
            list(z.infolist())  # validates the central directory; members come from _safe_zip_members
        except Exception as e:
            raise ValueError(f"cannot list zip ({e})")
        files = [(i, n) for i, n in _safe_zip_members(z)]
        total_uncompressed = 0
        for info, _ in files:
            try:
                total_uncompressed += max(0, int(info.file_size or 0))
            except Exception:
                logger.debug("zip size tally failed; skipping entry", exc_info=True)
                continue
        names_preview = [n for _, n in files[:MAX_ZIP_LISTED]]
        display = Path(str(path)).name
        # Vault stored names carry an "<id>_" prefix — hide it.
        _m = re.match(r"^[0-9a-f]{16}_(.+)$", display)
        if _m:
            display = _m.group(1)
        header = (
            f"[archive {display}: {len(files)} file(s)"
            + (f", {total_uncompressed} bytes uncompressed"
               if total_uncompressed else "")
            + "]"
        )
        if names_preview:
            header += "\nFiles: " + ", ".join(names_preview)
            if len(files) > len(names_preview):
                header += f" (+{len(files) - len(names_preview)} more)"
        if len(files) > MAX_ZIP_FILES:
            return (header + f"\n[Note: archive lists {len(files)} files "
                    f"(limit {MAX_ZIP_FILES}); showing file list only. "
                    "Split the archive to read contents.]").strip()
        if total_uncompressed > MAX_ZIP_UNCOMPRESSED_BYTES:
            return (header + "\n[Note: archive contents too large to expand "
                    "safely; showing file list only.]").strip()
        readable = _TEXT_EXTS | _HTML_EXTS | frozenset({"csv"})
        parts = [header]
        read_count = 0
        skipped: list[str] = []
        budget = MAX_DOCUMENT_CHARS
        for info, name in files:
            try:
                size = int(info.file_size or 0)
            except Exception:
                size = 0
            if size <= 0:
                continue
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext not in readable:
                skipped.append(name)
                continue
            if size > MAX_ZIP_FILE_BYTES:
                skipped.append(f"{name} (too large)")
                continue
            try:
                blob = z.read(info.filename)
            except RuntimeError:
                raise ValueError("archive is password-protected and cannot be read.")
            except Exception:
                skipped.append(f"{name} (unreadable)")
                continue
            try:
                text = _decode_inner_text(blob[:MAX_ZIP_FILE_BYTES + 1], name)
            except Exception:
                skipped.append(name)
                continue
            text = (text or "").strip()
            if not text:
                continue
            read_count += 1
            chunk = f"\n[file {name}]\n{text}"
            if len(chunk) > budget and budget > 0:
                chunk = chunk[:budget] + "\n[Note: member text truncated.]"
                parts.append(chunk)
                budget = 0
                break
            parts.append(chunk)
            budget -= len(chunk)
            if budget <= 0:
                break
        if skipped:
            parts.append("\n[Skipped non-text members: "
                         + ", ".join(skipped[:20])
                         + ("..." if len(skipped) > 20 else "") + "]")
        if read_count == 0:
            parts.append("\n[Note: no extractable text members found.]")
        return "\n".join(parts).strip()


_RTF_HEX_RE = re.compile(r"\\'([0-9a-fA-F]{2})")
_RTF_CTRL_RE = re.compile(r"\\[a-zA-Z]+\d*[ ]?")
_RTF_GROUP_RE = re.compile(r"\{\\\*[^}]*\}")


def _read_rtf_file(path) -> str:
    raw = path.read_bytes()
    if b"\x00" in raw[:8192]:
        raise ValueError("binary file, not an RTF document")
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
    if not text.lstrip().lower().startswith("{\\rtf"):
        raise ValueError("cannot parse rtf (missing {\\rtf header})")

    def _hex(m: re.Match) -> str:
        try:
            return bytes([int(m.group(1), 16)]).decode("latin-1")
        except Exception:
            return ""

    text = _RTF_HEX_RE.sub(_hex, text)
    text = text.replace("\\par", "\n").replace("\\line", "\n")
    text = text.replace("\\tab", " ").replace("\\emdash", "\u2014")
    text = text.replace("\\endash", "\u2013")
    text = _RTF_GROUP_RE.sub(" ", text)
    text = _RTF_CTRL_RE.sub(" ", text)
    text = text.replace("\\\\", "\\").replace("\\{", "{").replace("\\}", "}")
    text = text.replace("{", " ").replace("}", " ")
    lines = [" ".join(line.strip().split()) for line in text.splitlines()]
    cleaned = "\n".join(line for line in lines if line).strip()
    if not cleaned:
        raise ValueError("no extractable text in rtf")
    return cleaned + ("\n[Note: RTF formatting stripped — text only, "
                      "best-effort decode.]")


# Junk-class filtering for legacy-OLE strings lives in services/oletext
# (shared with services/kb.py, which has its own twin extractor for
# teaching windows + KB ingest). See that module for rationale.
from services.oletext import is_ole_garbage as _is_ole_garbage


def _ole_strings_text(blob: bytes, label: str) -> str:
    """Best-effort printable-strings extraction from OLE .doc/.ppt/.xls."""
    ascii_hits = re.findall(rb"[\x20-\x7e]{5,}", blob)
    utf16_hits = re.findall(rb"(?:[\x20-\x7e]\x00){5,}", blob)
    parts: list[str] = []
    for hit in ascii_hits:
        try:
            parts.append(hit.decode("ascii"))
        except Exception:
            logger.debug("ole ascii decode failed; skipping hit", exc_info=True)
            continue
    for hit in utf16_hits:
        try:
            parts.append(hit.decode("utf-16-le"))
        except Exception:
            logger.debug("ole utf16 decode failed; skipping hit", exc_info=True)
            continue
    junk = frozenset({
        "Root Entry", "WordDocument", "PowerPoint Document",
        "Microsoft Office", "SummaryInformation",
        "DocumentSummaryInformation",
    })
    # Image-heavy .ppt binaries need strict shape rules (short entropy
    # fragments, table identifiers); .doc/.xls keep lenient short-line
    # handling so real headings survive.
    strict = str(label or "").strip().lower() == ".ppt"
    seen: set[str] = set()
    kept: list[str] = []
    for piece in parts:
        text = " ".join(str(piece).split()).strip()
        if len(text) < 5 or text in junk or text in seen:
            continue
        # Skip font/style table noise: very long camel runs without spaces.
        if " " not in text and len(text) > 80:
            continue
        # Skip embedded-binary garbage (EXIF/XMP/JPEG entropy): it sorts
        # before real text in byte order and would otherwise exhaust the
        # output cap alone, hiding the document's actual content.
        if _is_ole_garbage(text, strict=strict):
            continue
        seen.add(text)
        kept.append(text)
        if sum(len(k) for k in kept) > MAX_DOCUMENT_CHARS:
            break
    cleaned = "\n".join(kept).strip()
    if not cleaned:
        raise ValueError(f"no extractable text in {label}")
    return cleaned + (f"\n[Note: legacy {label} extracted as raw text — "
                      "formatting, tables and order may be imperfect.]")


def _read_doc_file(path) -> str:
    return _ole_strings_text(path.read_bytes(), ".doc")


def _read_ppt_file(path) -> str:
    blob = path.read_bytes()
    # .ppt is OLE; many .ppt uploads are actually renamed .pptx (ZIP).
    # If ZIP, try the high-fidelity pptx parser first.
    if blob[:4] == b"PK\x03\x04":
        try:
            text = _read_pptx_file(path)
            if text and text.strip():
                return text
        except Exception:
            logger.debug("renamed-pptx parse failed; falling back to ole strings", exc_info=True)
        # Fall through to OLE strings for any remaining text.
    try:
        return _ole_strings_text(blob, ".ppt")
    except Exception as e:
        msg = str(e).lower()
        if "no extractable text" in msg:
            raise ValueError(
                "no extractable text in .ppt — likely scanned/image-only slides. "
                "Try Save As .pptx or Export to PDF with OCR, then re-upload."
            ) from e
        raise


def _read_xls_file(path) -> str:
    # High fidelity first (xlrd is optional — no hard dependency):
    # pandas reads .xls via xlrd when installed. Anything missing or
    # unparsable falls back to the OLE strings extractor below.
    try:
        import pandas as pd

        try:
            frames = pd.read_excel(str(path), sheet_name=None,
                                   engine="xlrd", nrows=5000)
        except Exception:
            frames = None
        if frames is not None:
            parts = []
            items = frames.items() if isinstance(frames, dict) \
                else [("Sheet1", frames)]
            for name, frame in items:
                try:
                    parts.append(f"[sheet {name}]\n{frame.to_string()}")
                except Exception:
                    logger.debug("xls sheet render failed; skipping sheet", exc_info=True)
                    continue
            text = "\n".join(parts).strip()
            if text:
                return text
    except Exception:
        logger.debug("xls pandas path failed; falling back to ole strings", exc_info=True)
    return _ole_strings_text(path.read_bytes(), ".xls")


def _odf_content_root(blob: bytes) -> Tuple[object, dict]:
    """Return (ElementTree root, namespace map) for an ODF content.xml."""
    import xml.etree.ElementTree as ET

    # XXE/billion-laughs guard: reject entity declarations before parsing.
    # Stdlib ET ignores external SYSTEM entities but expands internal ones,
    # so scan the WHOLE blob (a bomb can hide past any head window).
    if len(blob) > 5 * 1024 * 1024:
        raise ValueError("ODF content.xml too large")
    lowered = blob.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise ValueError("XML entities are not allowed in ODF content")
    try:
        # Prefer defusedxml when available (external entity forbid + entity expansion limit)
        try:
            import defusedxml.ElementTree as DET  # type: ignore
            root = DET.fromstring(blob, forbid_dtd=True, forbid_entities=True)
        except ImportError:
            # Fail closed without defusedxml: stdlib would expand internal
            # entities (billion-laughs). DTD already rejected above, but a
            # late <!ENTITY> past 8k could hide — re-scan fully, cheap.
            if b"<!entity" in blob.lower() or b"<!doctype" in blob.lower():
                raise ValueError("XML entities are not allowed in ODF content")
            root = ET.fromstring(blob)  # noqa: S314
        except Exception as e:
            raise ValueError(f"cannot parse document content ({e})")
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"cannot parse document content ({e})")
    ns = {
        "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
        "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
        "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
        "draw": "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
    }
    return root, ns


def _odf_para_text(elem, ns: dict) -> str:
    return " ".join("".join(elem.itertext()).split()).strip()


def _read_odt_file(path) -> str:
    try:
        with zipfile.ZipFile(str(path)) as z:
            info = z.getinfo("content.xml")
            if int(getattr(info, "file_size", 0) or 0) > 5 * 1024 * 1024:
                raise ValueError("odt content.xml too large")
            blob = z.read("content.xml")
    except KeyError:
        raise ValueError("odt archive has no content.xml")
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"cannot open odt ({e})")
    root, ns = _odf_content_root(blob)
    parts = []
    for elem in root.iter():
        tag = str(elem.tag or "")
        if tag in (f"{{{ns['text']}}}p", f"{{{ns['text']}}}h"):
            text = _odf_para_text(elem, ns)
            if text:
                parts.append(text)
    text = "\n".join(parts).strip()
    if not text:
        raise ValueError("no extractable text in odt")
    return text


def _read_ods_file(path) -> str:
    try:
        with zipfile.ZipFile(str(path)) as z:
            info = z.getinfo("content.xml")
            if int(getattr(info, "file_size", 0) or 0) > 5 * 1024 * 1024:
                raise ValueError("ods content.xml too large")
            blob = z.read("content.xml")
    except KeyError:
        raise ValueError("ods archive has no content.xml")
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"cannot open ods ({e})")
    root, ns = _odf_content_root(blob)
    tns = ns["table"]
    parts = []
    for table in root.iter(f"{{{tns}}}table"):
        name = table.get(f"{{{tns}}}name", "Sheet")
        parts.append(f"[sheet {name}]")
        for row in table.iter(f"{{{tns}}}table-row"):
            cells: list[str] = []
            for cell in row.iter(f"{{{tns}}}table-cell"):
                repeat = 1
                try:
                    repeat = max(1, min(20, int(cell.get(
                        f"{{{tns}}}number-columns-repeated", "1"))))
                except Exception:
                    repeat = 1
                cell_text = " ".join("".join(cell.itertext()).split())
                cells.extend([cell_text] * repeat)
                if len(cells) > 50:
                    cells = cells[:50]
                    break
            line = " | ".join(c for c in cells if c).strip()
            if line:
                parts.append(line)
            if len(parts) > 300:
                parts.append("[Note: sheet rows truncated.]")
                break
    text = "\n".join(parts).strip()
    if not text or text.startswith("[sheet") and len(parts) <= 1:
        raise ValueError("no extractable text in ods")
    return text


def _read_odp_file(path) -> str:
    try:
        with zipfile.ZipFile(str(path)) as z:
            info = z.getinfo("content.xml")
            if int(getattr(info, "file_size", 0) or 0) > 5 * 1024 * 1024:
                raise ValueError("odp content.xml too large")
            blob = z.read("content.xml")
    except KeyError:
        raise ValueError("odp archive has no content.xml")
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"cannot open odp ({e})")
    root, ns = _odf_content_root(blob)
    parts = []
    pages = list(root.iter(f"{{{ns['draw']}}}page"))
    for i, page in enumerate(pages, start=1):
        lines = []
        for elem in page.iter():
            tag = str(elem.tag or "")
            if tag in (f"{{{ns['text']}}}p", f"{{{ns['text']}}}h"):
                text = _odf_para_text(elem, ns)
                if text:
                    lines.append(text)
        if lines:
            parts.append(f"[slide {i}]\n" + "\n".join(lines))
    text = "\n".join(parts).strip()
    if not text:
        raise ValueError("no extractable text in odp")
    return text


def _docx_run_text(run: Any) -> str:
    """One run as lightweight markdown (bold/italic preserved, never raises)."""
    try:
        text = str(run.text or "")
    except Exception:
        return ""
    if not text.strip():
        return text
    try:
        bold = bool(run.bold)
    except Exception:
        bold = False
    try:
        italic = bool(run.italic)
    except Exception:
        italic = False
    if bold:
        return f"**{text}**"
    if italic:
        return f"*{text}*"
    return text


def _read_docx_file(path) -> str:
    from docx import Document

    doc = Document(str(path))
    parts = []
    for para in doc.paragraphs:
        # ponytail: style-mapped markdown (headings/lists) so converters
        # rebuild structure instead of guessing; plain paras unchanged.
        try:
            style = str(getattr(para.style, "name", "") or "")
        except Exception:
            style = ""
        text = "".join(_docx_run_text(r) for r in para.runs).strip() or (para.text or "").strip()
        if not text:
            continue
        if style.startswith("Heading"):
            level = {"Heading 1": "# ", "Heading 2": "## "}.get(style, "### ")
            parts.append(f"{level}{text}")
        elif style == "Title":
            parts.append(f"# {text}")
        elif style == "List Bullet":
            parts.append(f"- {text}")
        elif style.startswith("List Number"):
            parts.append(f"1. {text}")
        else:
            parts.append(text)
    for table in doc.tables:
        for row in table.rows:
            cells = [(cell.text or "").strip() for cell in row.cells]
            line = " | ".join(c for c in cells if c)
            if line:
                parts.append(line)
    return "\n".join(parts)


def _read_pptx_file(path) -> str:
    from pptx import Presentation

    prs = Presentation(str(path))
    try:
        from services.pptx_images import count_skipped_pictures as _count_skipped
        from services.pptx_images import iter_deck_pictures
        from services.pptx_images import picture_lines_for_slide as _pic_lines

        _pics_by_slide = {}
        for _num, _alt, _blob in iter_deck_pictures(prs):
            _pics_by_slide.setdefault(_num, []).append((_alt, _blob))

        def _vision_ocr(_blob):
            try:
                # Lazy: agent.* must not load at tools import time.
                from agent.vision import vision_ocr_bytes

                return str(vision_ocr_bytes(_blob) or "")
            except Exception:
                return ""

        def _vision_ocr_many(_blobs):
            try:
                from agent.vision import vision_ocr_many

                return vision_ocr_many(list(_blobs or []))
            except Exception:
                return [""] * len(list(_blobs or []))
    except Exception:
        logger.debug("pptx picture setup failed", exc_info=True)
        _pics_by_slide, _pic_lines = {}, None

        def _count_skipped(prs):
            return 0

        def _vision_ocr(_blob):
            return ""

        def _vision_ocr_many(_blobs):
            return [""] * len(list(_blobs or []))
    parts = []
    _img_counter = 0
    for i, slide in enumerate(prs.slides, start=1):
        lines = []
        for shape in slide.shapes:
            try:
                if shape.has_text_frame and shape.text:
                    text = str(shape.text).strip()
                    if text:
                        lines.append(text)
                if shape.has_table:
                    for row in shape.table.rows:
                        cells = [(cell.text or "").strip() for cell in row.cells]
                        line = " | ".join(c for c in cells if c)
                        if line:
                            lines.append(line)
            except Exception:
                logger.debug("ppt shape extract failed; skipping shape", exc_info=True)
                continue
        try:
            if _pic_lines is not None:
                _slide_pics = _pics_by_slide.get(i, [])
                if _slide_pics:
                    _pic_out, _pic_used = _pic_lines(
                        _slide_pics, _img_counter + 1, _vision_ocr,
                        _vision_ocr_many)
                    _img_counter += _pic_used
                    lines.extend(_pic_out)
        except Exception:
            logger.debug("pptx picture lines failed; skipping", exc_info=True)
        if lines:
            parts.append(f"[slide {i}]\n" + "\n".join(lines))
    try:
        _skipped = int(_count_skipped(prs) or 0)
    except Exception:
        _skipped = 0
    if _skipped > 0:
        parts.append(
            f"[Note: {_skipped} more image(s) in this file were skipped "
            "(image cap); content above covers what was read.]"
        )
    return "\n".join(parts)


def _read_xlsx_file(path) -> str:
    import pandas as pd

    try:
        frames = pd.read_excel(str(path), sheet_name=None, nrows=5000)
    except Exception as e:
        raise ValueError(f"cannot parse xlsx ({e})")
    parts = []
    items = frames.items() if isinstance(frames, dict) else [("Sheet1", frames)]
    # Cap sheets/cols/rows so a wide workbook can't OOM the worker.
    for idx, (name, frame) in enumerate(items):
        if idx >= 10:
            parts.append("[Note: only first 10 sheets shown.]")
            break
        try:
            if getattr(frame, "shape", (0, 0))[1] > 100:
                frame = frame.iloc[:, :100]
            parts.append(f"[sheet {str(name)[:80]}]\n{frame.head(500).to_string()}")
        except Exception:
            logger.debug("xlsx sheet render failed; skipping sheet", exc_info=True)
            continue
    text = "\n".join(parts)
    if len(text) > 20000:
        text = text[:20000] + "\n[Note: xlsx truncated.]"
    return text


@tool
def read_document(upload_id: str) -> str:
    """Read text from an uploaded document by its upload ID.

    Handles txt/md/html/xml/code, zip archives (lists members and
    extracts text-like members), legacy doc/ppt/xls/rtf/odt/ods/odp
    (best-effort), plus docx, pptx, and xlsx.
    Use ONLY with an upload ID the user actually provided in this
    conversation (from an attachment). Never invent IDs and never use
    filesystem paths — only opaque upload IDs are accepted.

    Args:
        upload_id: The 16-hex upload ID of a document owned by the user.

    Returns:
        Extracted text, or a STATUS= error marker on failure.
    """
    # ponytail: cache hit — second read is instant, no re-parse
    _hit = _DOC_CACHE.get(_DOC_CACHE.key_for(get_current_user_id(), upload_id))
    if _hit is not None:
        return _hit
    try:
        with obs_timed("document.parse") as rec:
            path, ext, error = _resolve_document(upload_id)
            if error is not None:
                rec["status"] = "denied" if "DENIED" in error else "failed"
                return error
            assert path is not None
            try:
                if ext in _TEXT_EXTS:
                    text = _read_text_file(path)
                elif ext in _HTML_EXTS:
                    text = _read_html_file(path)
                elif ext == "zip":
                    text = _read_zip_file(path)
                elif ext == "rtf":
                    text = _read_rtf_file(path)
                elif ext == "doc":
                    text = _read_doc_file(path)
                elif ext == "ppt":
                    text = _read_ppt_file(path)
                elif ext == "xls":
                    text = _read_xls_file(path)
                elif ext == "odt":
                    text = _read_odt_file(path)
                elif ext == "ods":
                    text = _read_ods_file(path)
                elif ext == "odp":
                    text = _read_odp_file(path)
                elif ext == "docx":
                    text = _read_docx_file(path)
                elif ext == "pptx":
                    text = _read_pptx_file(path)
                elif ext == "xlsx":
                    text = _read_xlsx_file(path)
                else:
                    rec["status"] = "failed"
                    return (
                        f"STATUS=INVALID tool=read_document: .{ext} is not a readable "
                        "document. Use read_pdf for PDFs or analyze_csv for CSVs."
                    )
            except Exception as e:
                rec["status"] = "failed"
                return f"STATUS=FAILED tool=read_document: {str(e)[:200]}"
        text = (text or "").strip()
        if not text:
            rec["status"] = "empty"
            return "STATUS=EMPTY tool=read_document: no extractable text."
        note = ""
        if len(text) > MAX_DOCUMENT_CHARS:
            text = text[:MAX_DOCUMENT_CHARS]
            note = "\n[Note: text truncated due to length.]"
        result = text + note
        _DOC_CACHE.set(_DOC_CACHE.key_for(get_current_user_id(), upload_id), result)
        return result
    except Exception as e:
        return f"STATUS=FAILED tool=read_document: {str(e)[:200]}"
