"""Message composer: plus button, text input, and send button.

Renders the input row and returns which buttons were clicked; the page
flow (app.py) owns what happens next (menu toggle, send handling).
"""

from typing import Tuple

import streamlit as st


def render_composer() -> Tuple[bool, bool]:
    """Render the composer row. Returns (plus_clicked, send_clicked)."""

    # Keyed container gives the shell a stable wrapper class
    # (st-key-composer) for positioning; widget keys below are unchanged.
    with st.container(key="composer"):

        col_plus, col_input, col_send = st.columns(
            [0.7, 8.3, 0.8],
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
                placeholder="Type your message...",
                label_visibility="collapsed",
                key=field_key,
            )


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
