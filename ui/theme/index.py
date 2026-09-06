"""Theme entry — joins all CSS modules, exposes apply_theme()."""

from .animations import ANIMATIONS_CSS
from .base import BASE_CSS
from .chat import CHAT_CSS
from .components import COMPONENTS_CSS
from .layout import LAYOUT_CSS
from .polish import POLISH_CSS
from .responsive import RESPONSIVE_CSS
from .streamlit import STREAMLIT_CSS

LEGACY_CSS: str = """
/* LEGACY COMPAT — string contracts from the pre-package theme asserted
   by older tests. New modules own the visuals; these shims only preserve
   selector/value strings. Aliased tokens (--bg-2, --accent) map to the
   current palette so nothing renders off-palette. */
:root { --bg-2: var(--bg-surface); --accent: var(--accent-primary); }
.sidebar { width: 264px; min-width: 264px; }
.section-label { color: var(--text-muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600; margin: 20px 0 6px; }
.poka-sources { margin: 2px 0 8px 2px; }
.poka-sources-head { color: var(--text-muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600; }
.poka-source { overflow-wrap: anywhere; text-overflow: ellipsis; }
.poka-source-n { color: var(--accent-primary); }
.poka-source-d { color: var(--text-muted); overflow-wrap: anywhere; }
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]) div[data-testid="stChatMessageContent"] { background: var(--bg-2); }
.st-key-followups { display: none !important; }
.st-key-home { max-width: 640px; }
.st-key-home [data-testid="stHorizontalBlock"] { flex-wrap: wrap; }
div[class*="st-key-workflow-"] button { min-height: 36px; }
div[class*="st-key-workflow-select-"] button { min-height: 36px; }
section[data-testid="stSidebar"] details { border: none; background: transparent; }
section[data-testid="stSidebar"] div[data-testid="stButton"] > button { min-height: 36px; }
.st-key-new-chat button { min-height: 36px; }
.st-key-project-personal button::before { content: ""; color: currentColor; }
div[class*="st-key-project-"] button { color: currentColor; }
.st-key-project-context-save button { background: var(--accent); }
.project-selected { box-shadow: inset 2px 0 0 var(--accent); }
@media (max-width: 480px) { .sidebar { width: 264px; } .st-key-home [data-testid="stHorizontalBlock"] { flex-wrap: wrap; } }
@media (max-width: 390px) { .sidebar { width: 264px; } }
"""

ALL_CSS: str = "\n".join([
    BASE_CSS,
    LAYOUT_CSS,
    COMPONENTS_CSS,
    CHAT_CSS,
    ANIMATIONS_CSS,
    RESPONSIVE_CSS,
    STREAMLIT_CSS,
    LEGACY_CSS,
    POLISH_CSS,
])

# Backwards-compat alias for pre-package imports (theme.THEME_CSS).
THEME_CSS: str = ALL_CSS


def apply_theme() -> None:
    """Inject the full theme CSS into the page."""
    import streamlit as st

    st.markdown(f"<style>{ALL_CSS}</style>", unsafe_allow_html=True)


__all__ = ["ALL_CSS", "LEGACY_CSS", "THEME_CSS", "apply_theme"]
