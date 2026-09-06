"""Poka visual theme — Phase 2 design system foundation.

Visual-only layer. Behavior contract unchanged:
- apply_theme() injects global CSS, no state, no side effects beyond styling.
- All Streamlit widget keys / session-state keys are preserved (see README).
- Later phases (sidebar/chat/composer redesign) build on these variables.
"""

import streamlit as st


THEME_CSS: str = """
/* ============================================================
   1. VARIABLES — single source of truth
   ============================================================ */
:root {
    /* Surfaces */
    --bg-0: #09090d;
    --bg-1: #0d0d12;
    --bg-2: #15151c;
    --bg-3: #1e1e27;

    /* Borders */
    --border: #292933;
    --border-strong: #3d3d48;

    /* Text */
    --text-1: #f2f2f5;
    --text-2: #a1a1aa;
    --text-3: #71717a;

    /* Accent — restrained use only (active, primary, focus, selected) */
    --accent: #7566ff;
    --accent-hover: #8474ff;
    --accent-pressed: #6354e6;
    --accent-wash: rgba(117, 102, 255, 0.12);

    /* Status */
    --success: #10B981;
    --warning: #F59E0B;
    --danger: #EF4444;

    /* Type scale */
    --fs-12: 12px;
    --fs-13: 13px;
    --fs-14: 14px;
    --fs-15: 15px;
    --fs-20: 20px;
    --fs-28: 28px;
    --fs-32: 32px;

    /* Spacing (4px grid) */
    --sp-4: 4px;
    --sp-8: 8px;
    --sp-12: 12px;
    --sp-16: 16px;
    --sp-20: 20px;
    --sp-24: 24px;
    --sp-32: 32px;

    /* Radius */
    --r-sm: 8px;
    --r-md: 12px;
    --r-lg: 16px;
    --r-xl: 20px;
    --r-pill: 999px;

    /* Shadows (subtle only) */
    --shadow-composer: 0 8px 28px rgba(0, 0, 0, 0.35);
    --shadow-menu: 0 12px 32px rgba(0, 0, 0, 0.4);
    --shadow-subtle: 0 1px 2px rgba(0, 0, 0, 0.2);

    /* Motion */
    --ease: ease;
    --dur: 160ms;
}


/* ============================================================
   2. GLOBAL / APP
   ============================================================ */
* {
    font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif;
}

.stApp {
    background: var(--bg-0);
    color: var(--text-1);
}

section[data-testid="stMain"] .block-container,
div[data-testid="stMainBlockContainer"] {
    max-width: 650px;
    /* In-flow clearance for the sticky composer (compact, not a hack). */
    padding-bottom: 24px !important;
}

header[data-testid="stHeader"] {
    background: rgba(9, 9, 13, 0.0);
}

header[data-testid="stHeader"] button {
    color: var(--text-2);
}

#MainMenu {
    visibility: hidden;
}

/* Hide the Deploy button (verified: stAppDeployButton in Streamlit 1.63).
   The header toolbar (menu, collapse) is left intact. */
div[data-testid="stAppDeployButton"],
.stAppDeployButton {
    display: none !important;
}

footer {
    visibility: hidden;
}

/* Subtle scrollbar — accent only on hover, restrained */
::-webkit-scrollbar {
    width: 8px;
    height: 8px;
}
::-webkit-scrollbar-track {
    background: transparent;
}
::-webkit-scrollbar-thumb {
    background: rgba(255, 255, 255, 0.12);
    border-radius: 4px;
}
::-webkit-scrollbar-thumb:hover {
    background: rgba(117, 102, 255, 0.45);
}


/* ============================================================
   3. TYPOGRAPHY
   ============================================================ */
.brand-title {
    font-size: var(--fs-28);
    font-weight: 600;
    letter-spacing: -0.02em;
    color: var(--text-1);
    margin: 0;
}

/* Small section labels — uppercase only where useful */
.section-label {
    color: var(--text-3);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-weight: 600;
    margin: var(--sp-12) 0 var(--sp-8);
}

div[data-testid="stChatMessageContent"] {
    font-size: var(--fs-15);
    line-height: 1.65;
    overflow-wrap: break-word;
    min-width: 0;
}

div[data-testid="stChatMessageContent"] p {
    margin: 0 0 12px;
}
div[data-testid="stChatMessageContent"] p:last-child {
    margin-bottom: 0;
}

div[data-testid="stChatMessageContent"] h1,
div[data-testid="stChatMessageContent"] h2,
div[data-testid="stChatMessageContent"] h3,
div[data-testid="stChatMessageContent"] h4 {
    font-weight: 600;
    letter-spacing: -0.01em;
    color: var(--text-1);
    margin: 20px 0 8px;
    line-height: 1.35;
}
div[data-testid="stChatMessageContent"] h1:first-child,
div[data-testid="stChatMessageContent"] h2:first-child,
div[data-testid="stChatMessageContent"] h3:first-child {
    margin-top: 0;
}
div[data-testid="stChatMessageContent"] h1 { font-size: var(--fs-20); }
div[data-testid="stChatMessageContent"] h2 { font-size: 17px; }
div[data-testid="stChatMessageContent"] h3,
div[data-testid="stChatMessageContent"] h4 { font-size: var(--fs-15); }

div[data-testid="stChatMessageContent"] ul,
div[data-testid="stChatMessageContent"] ol {
    margin: 0 0 12px;
    padding-left: 22px;
}
div[data-testid="stChatMessageContent"] li {
    margin: 4px 0;
}
div[data-testid="stChatMessageContent"] li::marker {
    color: var(--text-3);
}

div[data-testid="stChatMessageContent"] a {
    color: var(--accent-hover);
    text-decoration: none;
}
div[data-testid="stChatMessageContent"] a:hover {
    text-decoration: underline;
}

div[data-testid="stChatMessageContent"] blockquote {
    margin: 0 0 12px;
    padding: 8px 14px;
    border-left: 2px solid var(--border-strong);
    color: var(--text-2);
}
div[data-testid="stChatMessageContent"] blockquote p {
    margin-bottom: 6px;
}

div[data-testid="stChatMessageContent"] table {
    width: 100%;
    display: block;
    overflow-x: auto;
    border-collapse: collapse;
    font-size: var(--fs-14);
    margin: 0 0 12px;
}
div[data-testid="stChatMessageContent"] th,
div[data-testid="stChatMessageContent"] td {
    text-align: left;
    padding: 8px 12px;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
}
div[data-testid="stChatMessageContent"] td {
    white-space: normal;
}
div[data-testid="stChatMessageContent"] th {
    color: var(--text-2);
    font-size: var(--fs-12);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}
div[data-testid="stChatMessageContent"] tr:hover td {
    background: var(--bg-2);
}

div[data-testid="stChatMessageContent"] code {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    background: var(--bg-2);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 0.1rem 0.35rem;
    font-size: var(--fs-13);
    color: var(--text-1);
}

div[data-testid="stChatMessageContent"] pre {
    background: var(--bg-2);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 16px;
    margin: 0 0 12px;
    overflow-x: auto;
    line-height: 1.6;
}
div[data-testid="stChatMessageContent"] pre code {
    background: transparent;
    border: none;
    border-radius: 0;
    padding: 0;
    font-size: var(--fs-13);
    line-height: 1.6;
}

/* Attached images in chat — rounded, bordered, responsive */
div[data-testid="stImage"] {
    max-width: 320px;
}
div[data-testid="stImage"] img {
    max-width: 320px;
    width: 100%;
    border-radius: var(--r-md);
    border: 1px solid var(--border);
    box-shadow: none;
}


/* ============================================================
   4. BUTTON SYSTEM
   ============================================================ */
/* Reusable foundation classes for later phases (no dependency). */
.poka-btn-primary {
    background: var(--accent);
    color: #FFFFFF;
    border: 1px solid var(--accent);
    border-radius: var(--r-sm);
}
.poka-btn-secondary {
    background: transparent;
    color: var(--text-1);
    border: 1px solid transparent;
    border-radius: var(--r-sm);
}
/* Icon-button foundation: 36x36 circular, centers text or inline SVG. */
.poka-icon-btn {
    width: 36px;
    height: 36px;
    border-radius: var(--r-pill);
    display: inline-flex;
    align-items: center;
    justify-content: center;
}
.poka-icon-btn svg {
    width: 18px;
    height: 18px;
    display: block;
}

/* Generic Streamlit button cleanup — calm defaults */
div[data-testid="stBaseButton-secondary"] > button,
.stButton > button {
    transition: background-color var(--dur) var(--ease),
        border-color var(--dur) var(--ease),
        color var(--dur) var(--ease),
        transform var(--dur) var(--ease),
        box-shadow var(--dur) var(--ease);
}
div[data-testid="stBaseButton-secondary"] > button:active,
.stButton > button:active {
    transform: scale(0.97);
}


/* ============================================================
   5. INPUTS
   ============================================================ */
/* Sidebar search + generic text inputs: calm + visible focus */
section[data-testid="stSidebar"] div[data-testid="stTextInput"] input {
    background: var(--bg-2);
    border: 1px solid var(--border);
    border-radius: var(--r-sm);
    color: var(--text-1);
    font-size: var(--fs-14);
    min-height: 36px;
}
section[data-testid="stSidebar"] div[data-testid="stTextInput"] input::placeholder {
    color: var(--text-3);
    opacity: 1;
}
section[data-testid="stSidebar"] div[data-testid="stTextInput"] input:focus {
    border-color: var(--border-strong);
    box-shadow: 0 0 0 3px var(--accent-wash);
    outline: none;
}

section[data-testid="stSidebar"] div[data-testid="stTextArea"] textarea {
    background: var(--bg-2);
    border: 1px solid var(--border);
    border-radius: var(--r-sm);
    color: var(--text-1);
    font-size: var(--fs-14);
    line-height: 1.6;
}
section[data-testid="stSidebar"] div[data-testid="stTextArea"] textarea:focus {
    border-color: var(--border-strong);
    box-shadow: 0 0 0 3px var(--accent-wash);
    outline: none;
}


/* ============================================================
   6. CARDS — shared surface for memory / files / stats
   ============================================================ */
.stats-box {
    background: var(--bg-2);
    border: 1px solid var(--border);
    border-radius: var(--r-md);
    padding: 12px 14px;
}

div[data-testid="stDownloadButton"] > button {
    background: var(--bg-2);
    color: var(--text-1);
    border: 1px solid var(--border);
    border-radius: 10px;
    width: 100%;
}
div[data-testid="stDownloadButton"] > button:hover {
    background: var(--bg-3);
    border-color: var(--border-strong);
    color: #FFFFFF;
}


/* ============================================================
   7. MESSAGES — conversation
   ============================================================ */
/* Readable single column (~768px) with comfortable gutters */
section[data-testid="stMain"] .block-container,
div[data-testid="stMainBlockContainer"] {
    padding-left: 24px;
    padding-right: 24px;
}
section[data-testid="stMain"] {
    overflow-x: clip;
}

div[data-testid="stChatMessage"] {
    background: transparent;
    border: none;
    padding: var(--sp-8) 0;
    margin: 0 0 var(--sp-20);
    position: relative;
}
div[data-testid="stChatMessage"]:last-child {
    margin-bottom: 0;
}

/* Subtle appear only — no large slide/bounce */
@keyframes poka-fade {
    from { opacity: 0; }
    to { opacity: 1; }
}

/* Assistant identity — small mark, never dominates */
.poka-assistant-id {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: var(--fs-13);
    font-weight: 600;
    color: var(--text-2);
    margin: 0 0 4px 2px;
}
.poka-assistant-mark {
    width: 20px;
    height: 20px;
    border-radius: var(--r-pill);
    background: var(--accent-wash);
    border: 1px solid var(--border);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: var(--accent-hover);
}
.poka-assistant-mark svg {
    display: block;
    fill: currentColor;
}

/* Metadata row — time left, Copy action right (injected by page script) */
.poka-meta {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin: 4px 0 0 2px;
    min-height: 22px;
}
.poka-time {
    font-size: var(--fs-12);
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
}

/* Copy action — in-flow inside the meta row, never floating far away */
.poka-copy {
    position: static;
    display: inline-block;
    flex-shrink: 0;
    background: transparent;
    color: var(--text-3);
    border: 1px solid transparent;
    border-radius: var(--r-pill);
    font-size: 11px;
    padding: 3px 10px;
    margin: 0;
    cursor: pointer;
    opacity: 0;
    transition: opacity var(--dur) var(--ease),
        background-color var(--dur) var(--ease),
        color var(--dur) var(--ease),
        border-color var(--dur) var(--ease);
    z-index: 3;
}
.poka-copy:hover {
    color: var(--text-1);
    background: var(--bg-2);
    border-color: var(--border);
}
.poka-copy:focus-visible {
    opacity: 1;
    outline: 2px solid var(--accent);
    outline-offset: 2px;
}
div[data-testid="stChatMessage"]:hover .poka-copy {
    opacity: 1;
}
@media (hover: none) {
    .poka-copy { opacity: 1; }
}

/* Edit action row inside the user bubble — tight, belongs to message */
div[data-testid="stChatMessage"] [data-testid="stHorizontalBlock"] {
    gap: 8px !important;
}
div[class*="st-key-edit-"] {
    display: flex;
    justify-content: flex-end;
}
div[class*="st-key-edit-"] div[data-testid="stBaseButton-secondary"] > button,
div[class*="st-key-edit-"] .stButton > button {
    width: auto;
    background: transparent;
    border: 1px solid transparent;
    color: var(--text-3);
    font-size: var(--fs-12);
    border-radius: var(--r-pill);
    padding: 4px 14px;
    text-align: center;
    min-height: 30px;
    white-space: nowrap;
}
div[class*="st-key-edit-"] div[data-testid="stBaseButton-secondary"] > button:hover,
div[class*="st-key-edit-"] .stButton > button:hover {
    color: var(--text-1);
    border-color: var(--border);
    background: var(--bg-2);
    transform: none;
}

/* Legacy selector kept for compatibility */
div[class*="st-key-msgrow-"] {
    display: flex;
    justify-content: flex-end;
}
div[class*="st-key-msgrow-"] div[data-testid="stBaseButton-secondary"] > button,
div[class*="st-key-msgrow-"] .stButton > button {
    width: auto;
    background: transparent;
    border: 1px solid var(--border);
    color: var(--text-2);
    font-size: var(--fs-12);
    border-radius: var(--r-pill);
    padding: 4px 16px;
    text-align: center;
}
div[class*="st-key-msgrow-"] div[data-testid="stBaseButton-secondary"] > button:hover,
div[class*="st-key-msgrow-"] .stButton > button:hover {
    color: var(--text-1);
    border-color: var(--border-strong);
    background: var(--bg-2);
    transform: none;
}

/* Retry (existing retry-main widget in app.py) — quiet secondary */
.st-key-retry-main button {
    width: auto !important;
    background: transparent !important;
    border: 1px solid var(--border) !important;
    color: var(--text-1) !important;
    border-radius: var(--r-pill) !important;
    font-size: var(--fs-13) !important;
    padding: 6px 18px !important;
    min-height: 34px !important;
}
.st-key-retry-main button:hover {
    background: var(--bg-2) !important;
    border-color: var(--border-strong) !important;
}

/* Fresh-file downloads in chat — compact, not full-width */
section[data-testid="stMain"] div[data-testid="stDownloadButton"] > button {
    width: auto;
    max-width: 100%;
    min-height: 34px;
    font-size: var(--fs-13);
    padding: 7px 14px;
}

/* Error state — restyled Streamlit alert (detection/retry logic unchanged) */
section[data-testid="stMain"] div[data-testid="stAlert"] {
    background: rgba(239, 68, 68, 0.08);
    border: 1px solid rgba(239, 68, 68, 0.3);
    border-radius: var(--r-md);
    color: var(--text-1);
    font-size: var(--fs-14);
}
section[data-testid="stMain"] div[data-testid="stAlert"] p {
    margin: 0;
    line-height: 1.6;
}
section[data-testid="stMain"] div[data-testid="stAlert"] [data-testid="stAlertContentError"] {
    color: var(--text-1);
}
.poka-error {
    background: rgba(239, 68, 68, 0.08);
    border: 1px solid rgba(239, 68, 68, 0.3);
    border-radius: var(--r-md);
    padding: 12px 14px;
    max-width: 100%;
}
.poka-error-title {
    font-size: var(--fs-14);
    font-weight: 600;
    color: #FCA5A5;
    margin-bottom: 4px;
}
.poka-error-detail {
    font-size: var(--fs-13);
    line-height: 1.6;
    color: var(--text-2);
    overflow-wrap: break-word;
}

/* USER: right aligned, ~70%, bg-3, subtle border, NO purple glow */
div[data-testid="stChatMessage"]:has(
    div[data-testid="stChatMessageAvatarUser"]
) div[data-testid="stChatMessageAvatarUser"] {
    display: none;
}
div[data-testid="stChatMessage"]:has(
    div[data-testid="stChatMessageAvatarUser"]
) div[data-testid="stChatMessageContent"] {
    background: var(--bg-3);
    color: var(--text-1);
    padding: 12px 16px;
    border-radius: var(--r-lg) var(--r-lg) 4px var(--r-lg);
    border: 1px solid var(--border);
    box-shadow: none;
    margin-left: auto;
    max-width: 420px;
    animation: poka-fade var(--dur) var(--ease);
    font-size: var(--fs-15);
    line-height: 1.65;
}

/* ASSISTANT: subtle surface optimized for reading, no heavy card */
div[data-testid="stChatMessageAvatarAssistant"] {
    display: none;
}
div[data-testid="stChatMessage"]:has(
    div[data-testid="stChatMessageAvatarAssistant"]
) div[data-testid="stChatMessageContent"] {
    background: transparent;
    color: var(--text-1);
    padding: 8px 4px 12px;
    border-radius: 0;
    border: none;
    box-shadow: none;
    animation: poka-fade var(--dur) var(--ease);
    font-size: var(--fs-15);
    line-height: 1.65;
    max-width: 100%;
}

/* Calm typing indicator — soft pulse, no bounce */
.typing-indicator {
    display: flex;
    gap: 6px;
    padding: var(--sp-16) var(--sp-20);
    align-items: center;
}
.typing-indicator span {
    width: 7px;
    height: 7px;
    background: var(--text-3);
    border-radius: 50%;
    opacity: 0.45;
    animation: poka-pulse 1.2s infinite var(--ease);
}
.typing-indicator span:nth-child(2) { animation-delay: 0.15s; }
.typing-indicator span:nth-child(3) { animation-delay: 0.3s; }
@keyframes poka-pulse {
    0%, 100% { opacity: 0.3; }
    50% { opacity: 0.9; }
}

mark.search-hit {
    background: var(--accent-wash);
    color: inherit;
    border-radius: 3px;
    padding: 0 2px;
}


/* ============================================================
   8. SIDEBAR — foundation (~280px, hierarchy only)
   ============================================================ */
section[data-testid="stSidebar"] {
    background: var(--bg-1) !important;
    border-right: 1px solid var(--border);
    width: 230px;
}

section[data-testid="stSidebar"] .block-container {
    padding: 12px 12px 16px;
}

/* Tighter vertical rhythm so Files/Stats stay reachable */
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
    gap: 12px;
}

/* Primary action (New chat key) — accent reserved for important action */
section[data-testid="stSidebar"]
div[data-testid="stBaseButton-primary"] > button {
    background: var(--accent);
    color: #FFFFFF;
    border: 1px solid var(--accent);
    border-radius: var(--r-sm);
    width: 100%;
    transition: background-color var(--dur) var(--ease),
        transform var(--dur) var(--ease),
        box-shadow var(--dur) var(--ease);
}
section[data-testid="stSidebar"]
div[data-testid="stBaseButton-primary"] > button:hover {
    background: var(--accent-hover);
    border-color: var(--accent-hover);
    color: #FFFFFF;
    transform: translateY(-1px);
    box-shadow: var(--shadow-subtle);
}
section[data-testid="stSidebar"]
div[data-testid="stBaseButton-primary"] > button:active {
    background: var(--accent-pressed);
    transform: scale(0.98);
    box-shadow: none;
}

/* History / secondary rows */
section[data-testid="stSidebar"]
div[data-testid="stBaseButton-secondary"] > button {
    background: transparent;
    border: 1px solid transparent;
    border-radius: var(--r-sm);
    color: var(--text-1);
    text-align: left;
    width: 100%;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
section[data-testid="stSidebar"]
div[data-testid="stBaseButton-secondary"] > button:hover {
    background: var(--bg-3);
    border-color: var(--border);
    color: var(--text-1);
}

/* ---- Poka sidebar redesign (Phase 3, reuses Phase 2 vars) ---- */
.poka-brand {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 4px 2px 0;
}
.poka-mark {
    width: 28px;
    height: 28px;
    min-width: 28px;
    border-radius: var(--r-sm);
    background: var(--accent-wash);
    border: 1px solid var(--border);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: var(--accent-hover);
}
.poka-mark svg {
    width: 16px;
    height: 16px;
    display: block;
    fill: currentColor;
}
.poka-brand-text {
    display: flex;
    flex-direction: column;
    line-height: 1.2;
    min-width: 0;
}
.poka-word {
    font-size: var(--fs-15);
    font-weight: 600;
    letter-spacing: -0.01em;
    color: var(--text-1);
}
.poka-sub {
    font-size: var(--fs-12);
    color: var(--text-3);
}

/* Dynamic model line — subtle, not badge-heavy */
.poka-model {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 8px;
    padding: 0 2px;
    min-width: 0;
}
.poka-model-name {
    font-size: var(--fs-13);
    color: var(--text-2);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.poka-dot {
    width: 7px;
    height: 7px;
    min-width: 7px;
    border-radius: var(--r-pill);
    display: inline-block;
}
.poka-dot-online {
    background: var(--success);
}
.poka-dot-offline {
    background: var(--danger);
}
.poka-footer {
    margin-top: 4px;
    padding: 0 2px 4px;
}

.poka-divider {
    height: 1px;
    background: var(--border);
    margin: var(--sp-12) 0;
}

/* Mode — ONE segmented component (Fast/Deep buttons joined).
   The selected segment is disabled and styled as active; the other
   switches mode. Same deep_mode state, no second control. */
section[data-testid="stSidebar"] [data-testid="stHorizontalBlock"]:has(
    [class*="st-key-mode-"]
) {
    gap: 0 !important;
}
div[class*="st-key-mode-"] button {
    width: 100% !important;
    min-height: 36px !important;
    font-size: var(--fs-13) !important;
    font-weight: 600 !important;
    background: var(--bg-2) !important;
    border: 1px solid var(--border) !important;
    color: var(--text-2) !important;
    user-select: none !important;
    -webkit-user-select: none !important;
}
.st-key-mode-fast button {
    border-radius: 10px 0 0 10px !important;
    border-right: none !important;
}
.st-key-mode-deep button {
    border-radius: 0 10px 10px 0 !important;
}
div[class*="st-key-mode-"] button:hover:not(:disabled) {
    background: var(--bg-3) !important;
    border-color: var(--border) !important;
    color: var(--text-1) !important;
}
div[class*="st-key-mode-"] button:disabled {
    background: var(--bg-3) !important;
    border-color: var(--border-strong) !important;
    color: var(--text-1) !important;
    opacity: 1 !important;
    cursor: default !important;
}

/* New chat — prominent but fitted to the sidebar hierarchy */
.st-key-new-chat button {
    min-height: 38px !important;
    border-radius: 10px !important;
    font-size: var(--fs-14) !important;
    font-weight: 600 !important;
}

/* Search count + empty states — subtle */
.poka-match {
    color: var(--text-3);
    font-size: var(--fs-12);
    margin: 4px 2px 0;
}
.poka-empty {
    color: var(--text-3);
    font-size: var(--fs-12);
    margin: 4px 2px;
}
.poka-card-sub {
    color: var(--text-2);
    font-size: var(--fs-12);
    font-weight: 600;
    margin: 0 0 6px;
}

/* History rows — quiet, truncate naturally */
section[data-testid="stSidebar"] div[data-testid="column"] .stButton > button {
    padding-top: 8px;
    padding-bottom: 8px;
}
/* Rename trigger minimized; stays reachable on touch */
div[class*="st-key-rename-"] button {
    color: var(--text-3) !important;
    opacity: 0.55;
}
div[class*="st-key-rename-"] button:hover {
    opacity: 1;
    color: var(--text-1) !important;
}
@media (hover: none) {
    div[class*="st-key-rename-"] button {
        opacity: 1;
    }
}

/* Sidebar cards (bordered containers) — compact */
section[data-testid="stSidebar"] div[data-testid="stVerticalBlockBorderWrapper"] {
    background: var(--bg-2);
    border: 1px solid var(--border);
    border-radius: var(--r-md);
    padding: 10px 12px;
}

/* File rows */
.poka-file-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 2px;
    min-width: 0;
}
.poka-file-icon {
    color: var(--text-3);
    display: inline-flex;
    min-width: 14px;
}
.poka-file-icon svg {
    display: block;
}
.poka-file-name {
    font-size: var(--fs-13);
    color: var(--text-1);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

/* Compact quiet download buttons in sidebar */
section[data-testid="stSidebar"] div[data-testid="stDownloadButton"] > button {
    min-height: 32px;
    font-size: var(--fs-12);
    padding: 6px 10px;
}

/* Stats rows */
.poka-stat-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    margin-bottom: 8px;
}
.poka-stat-row:last-child {
    margin-bottom: 0;
}
.poka-stat-key {
    color: var(--text-2);
    font-size: var(--fs-13);
}
.poka-stat-val {
    color: var(--text-1);
    font-weight: 600;
    font-variant-numeric: tabular-nums;
}
.poka-stat-active {
    color: var(--text-1);
    font-weight: 600;
    font-size: var(--fs-12);
    max-width: 140px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

/* Clean files — danger-secondary, never primary-looking */
.st-key-clean-files button {
    background: transparent !important;
    border: 1px solid transparent !important;
    color: var(--text-2) !important;
}
.st-key-clean-files button:hover {
    background: rgba(239, 68, 68, 0.1) !important;
    border-color: rgba(239, 68, 68, 0.3) !important;
    color: var(--danger) !important;
    transform: none !important;
    box-shadow: none !important;
}


/* ============================================================
   9. COMPOSER — unified shell
   ============================================================ */
/* Sticky (in-flow) so the shell aligns with the main chat column and
   respects the sidebar automatically — no viewport centering math. */
.st-key-composer {
    position: sticky !important;
    bottom: 16px !important;
    width: min(575px, calc(100% - 32px)) !important;
    margin-left: auto !important;
    margin-right: auto !important;
    margin-top: 8px !important;
    background: var(--bg-1) !important;
    background-color: var(--bg-1) !important;
    border: 1px solid var(--border) !important;
    border-radius: 22px !important;
    padding: 6px 10px !important;
    box-sizing: border-box !important;
    z-index: 50 !important;
    box-shadow: var(--shadow-composer) !important;
    transition: border-color var(--dur) var(--ease),
        box-shadow var(--dur) var(--ease) !important;
}

.st-key-composer:focus-within {
    border-color: var(--border-strong) !important;
    box-shadow: var(--shadow-composer),
        0 0 0 3px var(--accent-wash) !important;
}

/* Layout reset inside composer */
.st-key-composer [data-testid="stVerticalBlock"] {
    gap: 0 !important;
}
.st-key-composer [data-testid="stHorizontalBlock"] {
    width: 100% !important;
    margin: 0 !important;
    padding: 0 !important;
    gap: 5px !important;
    align-items: center !important;
}
.st-key-composer [data-testid="column"] {
    min-width: 0 !important;
    padding: 0 !important;
    margin: 0 !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
}

/* Text input — reset inner BaseWeb surfaces so only the shell shows */
.st-key-composer [data-testid="stTextInput"] {
    width: 100% !important;
    margin: 0 !important;
    padding: 0 !important;
}
.st-key-composer [data-testid="stTextInput"] label {
    display: none !important;
}
/* Remove the native "Press Enter to apply" hint inside the composer shell.
   Enter-to-send keeps working via the existing page script; the shell
   itself is the obvious affordance. Sidebar search hints are untouched. */
.st-key-composer div[data-testid="InputInstructions"] {
    display: none !important;
}
.st-key-composer [data-testid="stTextInput"] div,
.st-key-composer [data-testid="stTextInput"] span,
.st-key-composer [data-testid="stTextInput"] input,
.st-key-composer [data-testid="stTextInput"] [data-baseweb],
.st-key-composer [data-testid="stTextInput"] [data-baseweb="input"],
.st-key-composer [data-testid="stTextInput"] [data-baseweb="base-input"] {
    background: transparent !important;
    background-color: transparent !important;
    background-image: none !important;
    border: 0 !important;
    border-width: 0 !important;
    border-style: none !important;
    border-color: transparent !important;
    border-radius: 0 !important;
    outline: none !important;
    box-shadow: none !important;
}
.st-key-composer [data-testid="stTextInput"] input {
    -webkit-appearance: none !important;
    appearance: none !important;
    width: 100% !important;
    color: var(--text-1) !important;
    -webkit-text-fill-color: var(--text-1) !important;
    font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif !important;
    font-size: var(--fs-15) !important;
    font-weight: 400 !important;
    line-height: 1.4 !important;
    padding: 8px !important;
    margin: 0 !important;
    min-height: 34px !important;
    height: 34px !important;
    caret-color: var(--accent-hover) !important;
}
.st-key-composer [data-testid="stTextInput"] input::placeholder {
    color: var(--text-3) !important;
    -webkit-text-fill-color: var(--text-3) !important;
    opacity: 1 !important;
}
.st-key-composer [data-testid="stTextInput"] *:focus,
.st-key-composer [data-testid="stTextInput"] *:focus-visible,
.st-key-composer [data-testid="stTextInput"] *:focus-within {
    background: transparent !important;
    background-color: transparent !important;
    border: 0 !important;
    box-shadow: none !important;
    outline: none !important;
}

/* Composer buttons — 32px circular icon buttons.
   Labels ("+"/"↑") stay in Python for keys/a11y; visuals are SVG icons. */
.st-key-composer button {
    width: 32px !important;
    height: 32px !important;
    min-width: 32px !important;
    max-width: 32px !important;
    padding: 0 !important;
    margin: 0 !important;
    border-radius: var(--r-pill) !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    font-size: 0 !important;
    line-height: 1 !important;
    box-shadow: none !important;
    transition: background-color var(--dur) var(--ease),
        border-color var(--dur) var(--ease),
        color var(--dur) var(--ease),
        transform var(--dur) var(--ease),
        box-shadow var(--dur) var(--ease),
        opacity var(--dur) var(--ease) !important;
}
.st-key-composer button::after {
    content: "" !important;
    width: 18px !important;
    height: 18px !important;
    flex-shrink: 0 !important;
    background-repeat: no-repeat !important;
    background-position: center !important;
    background-size: contain !important;
}
.st-key-composer button:disabled {
    opacity: 0.45 !important;
    cursor: not-allowed !important;
    transform: none !important;
    box-shadow: none !important;
}

/* Plus button — ghost with SVG plus icon */
.st-key-composer [data-testid="column"]:first-child button {
    background: transparent !important;
    background-color: transparent !important;
    border: 1px solid transparent !important;
    color: var(--text-2) !important;
}
.st-key-composer [data-testid="column"]:first-child button::after {
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='%23A1A1AA' stroke-width='1.8' stroke-linecap='round'%3E%3Cpath d='M8 3v10M3 8h10'/%3E%3C/svg%3E") !important;
}
.st-key-composer [data-testid="column"]:first-child button:hover {
    background: var(--bg-3) !important;
    background-color: var(--bg-3) !important;
    border-color: var(--border) !important;
    color: var(--text-1) !important;
}
.st-key-composer [data-testid="column"]:first-child button:hover::after {
    filter: brightness(1.35) !important;
}
.st-key-composer [data-testid="column"]:first-child button:active {
    transform: scale(0.95) !important;
}

/* Send button — circular accent with SVG arrow-up icon */
.st-key-composer [data-testid="column"]:last-child button {
    background: var(--accent) !important;
    background-color: var(--accent) !important;
    border: 1px solid var(--accent) !important;
    color: #ffffff !important;
}
.st-key-composer [data-testid="column"]:last-child button::after {
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='white' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M8 13.5v-11M3.5 7.5L8 3l4.5 4.5'/%3E%3C/svg%3E") !important;
}
.st-key-composer [data-testid="column"]:last-child button:hover {
    background: var(--accent-hover) !important;
    background-color: var(--accent-hover) !important;
    border-color: var(--accent-hover) !important;
    color: #ffffff !important;
    box-shadow: var(--shadow-subtle) !important;
}
.st-key-composer [data-testid="column"]:last-child button:active {
    background: var(--accent-pressed) !important;
    background-color: var(--accent-pressed) !important;
    border-color: var(--accent-pressed) !important;
    transform: scale(0.95) !important;
    box-shadow: none !important;
}


/* ============================================================
   10. ATTACHMENTS — chips + plus menu (anchored to composer)
   ============================================================ */
/* Anchor source lives on the composer shell (Phase 5). */
.st-key-composer {
    anchor-name: --poka-composer;
}
/* Precise anchor on the plus button wrapper (stable Poka key class). */
.st-key-composer_plus {
    anchor-name: --poka-plus;
}

.st-key-attachment-menu {
    position: fixed !important;
    position-anchor: --poka-plus !important;
    left: anchor(left) !important;
    top: anchor(top) !important;
    bottom: auto !important;
    translate: 0 calc(-100% - 8px) !important;
    width: 230px !important;
    max-width: calc(100vw - 32px) !important;
    max-height: calc(100vh - 200px) !important;
    overflow-y: auto !important;
    background: var(--bg-2) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--r-md) !important;
    padding: var(--sp-8) !important;
    z-index: 100 !important;
    box-shadow: var(--shadow-menu) !important;
}
/* Fallback for browsers without CSS anchor positioning */
@supports not (position-anchor: --poka-composer) {
    .st-key-attachment-menu {
        left: max(16px, calc(50% - 24rem)) !important;
        top: auto !important;
        bottom: 90px !important;
        translate: none !important;
        max-width: 300px !important;
    }
}
.st-key-attachment-menu button {
    width: 100% !important;
    min-height: 42px !important;
    border: none !important;
    border-radius: 9px !important;
    background: transparent !important;
    color: var(--text-1) !important;
    text-align: left !important;
    padding: 10px 12px 10px 38px !important;
    font-size: var(--fs-14) !important;
    box-shadow: none !important;
    position: relative !important;
}
.st-key-attachment-menu button:hover {
    background: var(--bg-3) !important;
    color: #FFFFFF !important;
}
.st-key-attachment-menu button::before {
    content: "" !important;
    position: absolute !important;
    left: 12px !important;
    top: 50% !important;
    translate: 0 -50% !important;
    width: 18px !important;
    height: 18px !important;
    background-repeat: no-repeat !important;
    background-position: center !important;
    background-size: contain !important;
}
.st-key-menu-files button::before {
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='%23A1A1AA' stroke-width='1.4' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M8 11V3M4.5 6.5L8 3l3.5 3.5'/%3E%3Cpath d='M2.5 11.5v2a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1v-2'/%3E%3C/svg%3E") !important;
}
.st-key-menu-camera button::before {
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='%23A1A1AA' stroke-width='1.4'%3E%3Crect x='1.5' y='4' width='13' height='9' rx='2'/%3E%3Ccircle cx='8' cy='8.5' r='2.5'/%3E%3Cpath d='M5.5 4l1-1.5h3l1 1.5'/%3E%3C/svg%3E") !important;
}
.st-key-menu-search button::before {
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='%23A1A1AA' stroke-width='1.4'%3E%3Ccircle cx='8' cy='8' r='6'/%3E%3Cpath d='M2 8h12M8 2c-3.5 3.5-3.5 8.5 0 12M8 2c3.5 3.5 3.5 8.5 0 12'/%3E%3C/svg%3E") !important;
}

/* Popover header + upload limits subtext */
.poka-menu-head {
    color: var(--text-1);
    font-size: var(--fs-13);
    font-weight: 600;
    margin: 4px 4px 2px;
}
.poka-menu-sub {
    color: var(--text-3);
    font-size: var(--fs-12);
    margin: 2px 4px 4px 38px;
}

/* Pickers live inside the menu card — compact, never overflowing */
.st-key-attachment-menu div[data-testid="stFileUploader"],
.st-key-attachment-menu div[data-testid="stCameraInput"] {
    margin-top: 4px !important;
    max-width: 100% !important;
    padding: 6px !important;
}
.st-key-attachment-menu div[data-testid="stFileUploader"] button {
    padding: 6px 10px !important;
    min-height: 32px !important;
}

/* Chip row — horizontal, wrapping, composer-aligned, never overflowing */
.poka-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    width: min(575px, 100%);
    margin: 0 auto 8px;
}
.poka-chip {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    background: var(--bg-2);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 7px 12px;
    font-size: var(--fs-13);
    color: var(--text-1);
    max-width: 100%;
    min-width: 0;
}
.poka-chip-icon {
    color: var(--text-3);
    display: inline-flex;
    min-width: 14px;
}
.poka-chip-icon svg {
    display: block;
}
.poka-chip-name {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    min-width: 0;
}

/* Remove control — compact circular X icon (label "x" kept for key/a11y) */
.st-key-rm-attach button {
    width: 30px !important;
    height: 30px !important;
    min-width: 30px !important;
    max-width: 30px !important;
    border-radius: var(--r-pill) !important;
    background: var(--bg-2) !important;
    border: 1px solid var(--border) !important;
    color: var(--text-2) !important;
    font-size: 0 !important;
    line-height: 1 !important;
    padding: 0 !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
}
.st-key-rm-attach button::after {
    content: "" !important;
    width: 14px !important;
    height: 14px !important;
    background-repeat: no-repeat !important;
    background-position: center !important;
    background-size: contain !important;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='%23A1A1AA' stroke-width='1.8' stroke-linecap='round'%3E%3Cpath d='M4 4l8 8M12 4l-8 8'/%3E%3C/svg%3E") !important;
}
.st-key-rm-attach button:hover {
    border-color: rgba(239, 68, 68, 0.4) !important;
    background: rgba(239, 68, 68, 0.1) !important;
}

/* Web-search indicator pill — subtle, not bright purple text */
.poka-search-pill {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    background: var(--accent-wash);
    border: 1px solid rgba(117, 102, 255, 0.3);
    color: var(--text-2);
    font-size: var(--fs-12);
    border-radius: var(--r-pill);
    padding: 6px 13px;
}
.poka-search-mark {
    color: var(--accent-hover);
    display: inline-flex;
}
.poka-search-mark svg {
    display: block;
    fill: currentColor;
}

div[data-testid="stFileUploader"] {
    background: var(--bg-2);
    border: 1px solid var(--border);
    border-radius: var(--r-md);
    padding: var(--sp-8) var(--sp-12);
}
div[data-testid="stFileUploader"] button {
    background: var(--bg-1);
    color: var(--text-1);
    border: 1px solid var(--border);
    border-radius: var(--r-sm);
}
div[data-testid="stFileUploader"] button:hover {
    border-color: var(--border-strong);
    color: #FFFFFF;
}

div[data-testid="stCameraInput"] {
    border: 1px solid var(--border);
    border-radius: var(--r-md);
    padding: var(--sp-8);
}


/* ============================================================
   11. ACCESSIBILITY — focus must always stay visible
   ============================================================ */
:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
}
.st-key-composer [data-testid="stTextInput"] *:focus-visible {
    outline: none !important;
}


/* ============================================================
   12. HOME / EMPTY STATE
   ============================================================ */
.poka-home {
    text-align: center;
    max-width: 600px;
    margin: 0 auto;
    padding: 28px 24px 0;
}
.poka-home-mark {
    width: 36px;
    height: 36px;
    border-radius: var(--r-pill);
    background: var(--accent-wash);
    border: 1px solid var(--border);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: var(--accent-hover);
}
.poka-home-mark svg {
    display: block;
    fill: currentColor;
}
.poka-home h1 {
    font-size: 30px;
    font-weight: 600;
    letter-spacing: -0.02em;
    color: var(--text-1);
    margin: 10px 0 0;
    line-height: 1.25;
}
.poka-home p {
    font-size: var(--fs-15);
    line-height: 1.6;
    color: var(--text-2);
    margin: 8px auto 0;
    max-width: 560px;
}

/* Suggestion grid — capped to the home column width */
.st-key-home {
    max-width: 600px;
    margin: 0 auto;
}
/* Suggestion cards — lightweight bordered cards, native buttons inside */
.st-key-home div[data-testid="stVerticalBlockBorderWrapper"] {
    background: var(--bg-2);
    border: 1px solid var(--border);
    border-radius: var(--r-md);
    padding: 12px 14px;
    transition: background-color var(--dur) var(--ease),
        border-color var(--dur) var(--ease);
}
.st-key-home div[data-testid="stVerticalBlockBorderWrapper"]:hover {
    background: var(--bg-3);
    border-color: var(--border-strong);
}
.st-key-home div[class*="st-key-suggest-"] button {
    width: 100% !important;
    min-height: 32px !important;
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    color: var(--text-1) !important;
    font-size: var(--fs-14) !important;
    font-weight: 600 !important;
    text-align: left !important;
    padding: 2px 2px 2px 30px !important;
    white-space: normal !important;
    position: relative !important;
}
.st-key-home div[class*="st-key-suggest-"] button::before {
    content: "" !important;
    position: absolute !important;
    left: 2px !important;
    top: 50% !important;
    translate: 0 -50% !important;
    width: 17px !important;
    height: 17px !important;
    background-repeat: no-repeat !important;
    background-position: center !important;
    background-size: contain !important;
    opacity: 0.85 !important;
}
.st-key-suggest-0 button::before {
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='%23A1A1AA' stroke-width='1.4'%3E%3Crect x='2' y='2.5' width='12' height='8' rx='1.5'/%3E%3Cpath d='M6 13.5h4M8 10.5v3' stroke-linecap='round'/%3E%3C/svg%3E") !important;
}
.st-key-suggest-1 button::before {
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='%23A1A1AA' stroke-width='1.4'%3E%3Cpath d='M3 1.5h4.5L11 5v9.5H3z'/%3E%3Cpath d='M7.5 1.5V5H11'/%3E%3C/svg%3E") !important;
}
.st-key-suggest-2 button::before {
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='%23A1A1AA' stroke-width='1.4'%3E%3Ccircle cx='8' cy='8' r='6'/%3E%3Cpath d='M2 8h12M8 2c-3.5 3.5-3.5 8.5 0 12M8 2c3.5 3.5 3.5 8.5 0 12'/%3E%3C/svg%3E") !important;
}
.st-key-suggest-3 button::before {
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='%23A1A1AA'%3E%3Cpath d='M8 0l1.8 5.6L15 7l-4 3.6L12.2 16 8 12.8 3.8 16 5 10.6 1 7l5.2-1.4z'/%3E%3C/svg%3E") !important;
}
.st-key-home div[data-testid="stCaptionContainer"] {
    text-align: left;
    color: var(--text-2);
    font-size: var(--fs-12);
}


/* ============================================================
   13. RESPONSIVE — foundations (layout redesign is later)
   ============================================================ */
/* Laptop */
@media (max-width: 1100px) {
    section[data-testid="stMain"] .block-container,
    div[data-testid="stMainBlockContainer"] {
        max-width: 620px;
    }
    .st-key-composer {
        width: min(575px, calc(100% - 32px)) !important;
    }
}

/* Tablet */
@media (max-width: 900px) {
    section[data-testid="stSidebar"] {
        width: 220px;
    }
    div[data-testid="stChatMessage"]:has(
        div[data-testid="stChatMessageAvatarUser"]
    ) div[data-testid="stChatMessageContent"] {
        max-width: 80%;
    }
}

/* Mobile */
@media (max-width: 700px) {
    section[data-testid="stMain"] .block-container,
    div[data-testid="stMainBlockContainer"] {
        padding-left: 16px;
        padding-right: 16px;
    }
    .st-key-composer {
        width: calc(100% - 24px) !important;
        bottom: 12px !important;
        padding: 6px 8px !important;
        border-radius: 18px !important;
    }
    .st-key-composer [data-testid="stHorizontalBlock"] {
        gap: 4px !important;
    }
    .st-key-composer button {
        width: 32px !important;
        height: 32px !important;
        min-width: 32px !important;
        max-width: 32px !important;
    }
    .st-key-composer [data-testid="stTextInput"] input {
        font-size: var(--fs-14) !important;
        min-height: 34px !important;
        height: 34px !important;
        padding: 8px 6px !important;
    }
    .st-key-attachment-menu {
        width: 230px !important;
        max-width: calc(100vw - 32px) !important;
    }
    div[data-testid="stChatMessage"]:has(
        div[data-testid="stChatMessageAvatarUser"]
    ) div[data-testid="stChatMessageContent"] {
        max-width: 85%;
    }
    div[data-testid="stImage"],
    div[data-testid="stImage"] img {
        max-width: 100%;
    }
    div[class*="st-key-edit-"] div[data-testid="stBaseButton-secondary"] > button,
    div[class*="st-key-edit-"] .stButton > button {
        padding: 4px 10px;
    }
    div[data-testid="stChatMessageContent"] pre {
        padding: 12px;
    }
    .poka-error {
        padding: 10px 12px;
    }
    .poka-home {
        padding: 20px 16px 0;
    }
    .poka-home h1 {
        font-size: 26px;
    }
}

/* Small mobile */
@media (max-width: 480px) {
    .brand-title {
        font-size: 24px;
    }
    .st-key-composer {
        border-radius: var(--r-lg) !important;
    }
}
"""


def apply_theme() -> None:
    """Inject the Poka theme into the page."""
    st.markdown("<style>" + THEME_CSS + "</style>", unsafe_allow_html=True)
