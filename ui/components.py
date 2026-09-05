"""Reusable presentation helpers: formatting, badges, export, indicators.

Pure UI building blocks with no session-state or backend coupling:
callers pass values in and render the returned output. Imported by the
page flow (app.py) and the UI sections (ui/chat.py, ui/sidebar.py).
"""

import re
from typing import Any, Dict, List

import streamlit as st

from services.timeutil import format_local, utcnow_stamp


def tier_status(
    tier_name: str,
) -> tuple:
    """Map a tier name to badge class and marker."""

    if tier_name == "Muse Spark 1.3":
        return (
            "online",
            "●",
        )

    if (
        tier_name.startswith("Gemini")
        or tier_name.startswith("Nemotron")
    ):
        return (
            "fallback",
            "◐",
        )

    return (
        "offline",
        "○",
    )


def _format_time(iso_str: str) -> str:
    """Format an ISO timestamp in local time, "" when missing."""
    return format_local(iso_str)


def _highlight_query(text: str, query: str) -> str:
    """Wrap case-insensitive query matches in <mark>, preserving structure.

    Code fences, inline code, images, and links are never touched so
    highlighting cannot corrupt Markdown formatting or URLs.
    """
    if not query.strip():
        return text
    parts = re.split(
        r"(```.*?```|`[^`\n]+`|!\[[^\]]*\]\([^)]*\)|\[[^\]]*\]\([^)]*\))",
        text,
        flags=re.DOTALL,
    )
    out: List[str] = []
    for i, part in enumerate(parts):
        if i % 2 == 1 or not part.strip():
            out.append(part)
            continue
        out.append(
            re.sub(
                re.escape(query),
                lambda m: f'<mark class="search-hit">{m.group(0)}</mark>',
                part,
                flags=re.IGNORECASE,
            )
        )
    return "".join(out)


def _export_chat_to_markdown(messages: List[Dict[str, Any]]) -> str:
    """Render the conversation as a Markdown document for download."""
    lines: List[str] = [
        "# Poka Chat Export\n",
        f"Exported: {utcnow_stamp('%Y-%m-%d %H:%M')}\n\n",
    ]
    for m in messages:
        role = "You" if m.get("role") == "user" else "Poka"
        time_str = _format_time(str(m.get("time", "")))
        stamp = f" — {time_str}" if time_str else ""
        lines.append(f"## {role}{stamp}\n\n{m.get('content', '')}\n\n---\n\n")
    return "".join(lines)


def _show_typing() -> Any:
    """Show the three-dot typing indicator; caller empties the box."""
    box = st.empty()
    box.markdown(
        '<div class="typing-indicator"><span></span><span></span><span></span></div>',
        unsafe_allow_html=True,
    )
    return box


# Enter-to-send wiring plus the auto-scroll follower and hover copy
# buttons. Rendered once per page via components.html(...). The selectors
# degrade gracefully (main section fallback) on older Streamlit builds.
COMPOSER_SCRIPT: str = """
<script>
(function () {
    const win = window.parent;
    const doc = win.document;

    /* --- Enter-to-send (rebound to the fresh input after every send,
       since each send recreates the input with a new widget key) --- */
    const scope = doc.querySelector(".st-key-composer")
        || doc.querySelector('section[data-testid="stMain"]');
    if (scope) {
        const input = scope.querySelector('div[data-testid="stTextInput"] input');
        if (input && !input.dataset.enterBound) {
            input.dataset.enterBound = "1";
            input.setAttribute("autocomplete", "off");
            input.setAttribute("autocapitalize", "off");
            input.setAttribute("autocorrect", "off");
            input.addEventListener("keydown", function (e) {
                if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
                    e.preventDefault();
                    const box = input.closest(".st-key-composer") || scope;
                    const btns = box.querySelectorAll("button");
                    const send = btns[btns.length - 1];
                    if (send) send.click();
                }
            });
        }
    }

    /* --- auto-scroll follower (bound once per page) --- */
    if (doc.__pokaScrollBound) return;
    doc.__pokaScrollBound = true;

    function pageScroller() {
        const docEl = doc.scrollingElement || doc.documentElement;
        const section = doc.querySelector('section[data-testid="stMain"]');
        const cands = [docEl, doc.body, section];
        for (const el of cands) {
            if (el && el.scrollHeight > el.clientHeight + 10) return el;
        }
        return docEl || doc.body;
    }
    function nearBottom() {
        try {
            const y = win.scrollY || win.pageYOffset || 0;
            const h = doc.body ? doc.body.scrollHeight : 0;
            if (h > win.innerHeight + 10) {
                return h - y - win.innerHeight < 180;
            }
        } catch (err) { /* fall through to element check */ }
        const el = pageScroller();
        if (!el) return true;
        return el.scrollHeight - el.scrollTop - el.clientHeight < 180;
    }
    function goBottom(smooth) {
        const el = pageScroller();
        if (!el) return;
        try {
            if (smooth && el.scrollTo) {
                el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
                return;
            }
        } catch (err) { /* fall through */ }
        el.scrollTop = el.scrollHeight;
    }

    let wasNear = true;
    try {
        win.addEventListener("scroll", function () { wasNear = nearBottom(); }, true);
    } catch (err) { /* ignore */ }
    setTimeout(function () { goBottom(false); }, 400);

    new MutationObserver(function (muts) {
        let hasChat = false;
        for (const m of muts) {
            const nodes = m.addedNodes || [];
            for (const n of nodes) {
                if (n.nodeType !== 1) continue;
                try {
                    if (n.matches('[data-testid="stChatMessage"]') || n.querySelector('[data-testid="stChatMessage"]')) {
                        hasChat = true;
                        break;
                    }
                } catch (err) { /* ignore */ }
            }
            if (hasChat) break;
        }
        if (hasChat && wasNear) {
            goBottom(true);
            setTimeout(function () { goBottom(false); }, 450);
        }
        try { wasNear = nearBottom(); } catch (err) { /* ignore */ }
    }).observe(doc.body, { childList: true, subtree: true });

    /* --- Copy buttons (hover to reveal) ---
       Placed inside the message meta row when present (time + Copy side
       by side), otherwise directly after the message content. Copy text
       source and clipboard behavior are unchanged. */
    function armCopyButtons() {
        const nodes = doc.querySelectorAll('div[data-testid="stChatMessage"]');
        for (const node of nodes) {
            if (node.dataset.pokaActions) continue;
            const content = node.querySelector('div[data-testid="stChatMessageContent"]');
            if (!content) continue;
            node.dataset.pokaActions = "1";
            const btn = doc.createElement("button");
            btn.textContent = "Copy";
            btn.className = "poka-copy";
            btn.type = "button";
            btn.addEventListener("click", function (ev) {
                ev.stopPropagation();
                const text = content.innerText || content.textContent || "";
                const done = function () {
                    btn.textContent = "Copied";
                    setTimeout(function () { btn.textContent = "Copy"; }, 1200);
                };
                const fallbackCopy = function () {
                    try {
                        const ta = doc.createElement("textarea");
                        ta.value = text;
                        ta.style.position = "fixed";
                        ta.style.opacity = "0";
                        doc.body.appendChild(ta);
                        ta.select();
                        doc.execCommand("copy");
                        doc.body.removeChild(ta);
                        done();
                    } catch (err) {
                        btn.textContent = "Failed";
                    }
                };
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(text).then(done, fallbackCopy);
                } else {
                    fallbackCopy();
                }
            });
            const meta = node.querySelector('.poka-meta');
            if (meta) {
                meta.appendChild(btn);
            } else if (content.nextSibling) {
                content.parentNode.insertBefore(btn, content.nextSibling);
            } else {
                content.parentNode.appendChild(btn);
            }
        }
    }
    armCopyButtons();
    new MutationObserver(function () { armCopyButtons(); }).observe(doc.body, { childList: true, subtree: true });
})();
</script>
"""
