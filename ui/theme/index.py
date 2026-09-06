"""Theme entry — joins all CSS modules, exposes apply_theme()."""

from .animations import ANIMATIONS_CSS
from .base import BASE_CSS
from .chat import CHAT_CSS
from .components import COMPONENTS_CSS
from .layout import LAYOUT_CSS
from .responsive import RESPONSIVE_CSS
from .streamlit import STREAMLIT_CSS

ALL_CSS: str = "\n".join([
    BASE_CSS,
    LAYOUT_CSS,
    COMPONENTS_CSS,
    CHAT_CSS,
    ANIMATIONS_CSS,
    RESPONSIVE_CSS,
    STREAMLIT_CSS,
])


def apply_theme() -> None:
    """Inject the full theme CSS into the page."""
    import streamlit as st

    st.markdown(f"<style>{ALL_CSS}</style>", unsafe_allow_html=True)


__all__ = ["ALL_CSS", "apply_theme"]
