"""Message composer: plus button, text input, and send button.

Renders the input row and returns which buttons were clicked; the page
flow (app.py) owns what happens next (menu toggle, send handling).
"""

from typing import Tuple

import streamlit as st


def render_composer() -> Tuple[bool, bool]:
    """Render the composer row. Returns (plus_clicked, send_clicked).

    The Fast/Deep mode toggle lives here as a ghost label on the right
    side of the bar. It flips the shared ``deep_mode`` session flag
    and reruns; answering still reads that flag via application.session.

    New theme: input area is wrapped in a keyed container (st-key-
    composer-dock: centered bottom glass blur). Attachment chips render
    INSIDE the dock via the slot below (single render site — do not also
    call the chip renderer in app.py; duplicate remove-keys would crash).
    Real containers are used instead of split open/close divs so the
    browser nests content correctly. Widget keys below are unchanged.
    """

    # Dock wrapper: keyed container -> stable .st-key-composer-dock class.
    with st.container(key="composer-dock"):
        # Chips slot INSIDE the dock, not below it (single render site).
        with st.container(key="composer-chips"):
            from ui.uploads import render_attachment_chip as _render_chips_in_dock

            _render_chips_in_dock()

        # Keyed container gives the shell a stable wrapper class
        # (st-key-composer) for positioning; widget keys below are unchanged.
        # Order mirrors the reference pill: add on the left, text in the
        # middle, mode toggle + send on the right.
        with st.container(key="composer"):
            col_plus, col_input, col_mode, col_send = st.columns(
                [0.9, 6.3, 1.4, 0.9],
                gap="small",
                vertical_alignment="center",
            )

            # --------------------------------------------------------
            # PLUS BUTTON
            # --------------------------------------------------------

            with col_plus:
                plus_clicked = st.button(
                    "+",
                    key="composer_plus",
                    help="Attachments and tools",
                )

            # --------------------------------------------------------
            # INPUT
            # --------------------------------------------------------

            with col_input:
                field_key = (
                    f"composer_input_"
                    f"{st.session_state.composer_key}"
                )
                st.text_input(
                    "Message",
                    placeholder="Ask anything",
                    label_visibility="collapsed",
                    key=field_key,
                )

            # --------------------------------------------------------
            # MODE TOGGLE (ghost label on the right, like Think)
            # --------------------------------------------------------

            with col_mode:
                _is_deep = bool(st.session_state.get("deep_mode", False))
                if st.button(
                    "Deep" if _is_deep else "Fast",
                    key="composer-mode",
                    help="Switch to Fast mode" if _is_deep else "Switch to Deep mode",
                ):
                    st.session_state.deep_mode = not _is_deep
                    st.rerun()

            # --------------------------------------------------------
            # SEND
            # --------------------------------------------------------

            with col_send:
                send_clicked = st.button(
                    "↑",
                    key="composer_send",
                    help="Send message",
                )

    return plus_clicked, send_clicked
