"""Poka visual theme — premium dark workspace.

Visual-only layer. Behavior contract unchanged:
- apply_theme() injects global CSS, no state, no side effects beyond styling.
- All Streamlit widget keys / session-state keys are preserved (see README).
- All JS-required selectors (.st-key-*, stChatMessage hooks, BaseWeb
  input resets, composer + attachment-menu anchors) are preserved.
"""

import streamlit as st


THEME_CSS: str = """
/* 1. TOKENS — single source of truth (no arbitrary values below) */
:root {
    --bg-0: #08080c; --bg-1: #0e0e13; --bg-2: #14141b; --bg-3: #1c1c25;
    --border: #23232e; --border-strong: #373743;
    --text-1: #f4f4f6; --text-2: #a8a8b3; --text-3: #6f6f7b;
    --accent: #7566ff; --accent-hover: #8575ff; --accent-pressed: #6354e6;
    --accent-wash: rgba(117, 102, 255, 0.12);
    --success: #10B981; --warning: #F59E0B; --danger: #EF4444;
    --fs-12: 12px; --fs-14: 14px; --fs-15: 15px; --fs-16: 16px;
    --fs-18: 18px; --fs-20: 20px; --fs-24: 24px; --fs-32: 32px;
    --sp-4: 4px; --sp-8: 8px; --sp-12: 12px; --sp-16: 16px;
    --sp-20: 20px; --sp-24: 24px; --sp-32: 32px;
    --r-sm: 8px; --r-md: 12px; --r-lg: 16px; --r-pill: 999px;
    --shadow-subtle: 0 1px 2px rgba(0, 0, 0, 0.28);
    --shadow-composer: 0 12px 32px rgba(0, 0, 0, 0.45);
    --shadow-menu: 0 16px 40px rgba(0, 0, 0, 0.5);
    --ease: cubic-bezier(0.2, 0, 0, 1); --dur: 180ms;
}
/* 2. GLOBAL / APP (single container-width rule) */
* { font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif; }
.stApp { background: var(--bg-0); color: var(--text-1); -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility; }
section[data-testid="stMain"] { overflow-x: clip; }
section[data-testid="stMain"] .block-container, div[data-testid="stMainBlockContainer"] { max-width: 680px; padding-left: var(--sp-24); padding-right: var(--sp-24); padding-bottom: var(--sp-24) !important; }
header[data-testid="stHeader"] { background: rgba(8, 8, 12, 0.0); }
header[data-testid="stHeader"] button { color: var(--text-2); }
#MainMenu { visibility: hidden; }
div[data-testid="stAppDeployButton"], .stAppDeployButton { display: none !important; }
footer { visibility: hidden; }
::-webkit-scrollbar { width: var(--sp-8); height: var(--sp-8); }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.1); border-radius: var(--sp-4); }
::-webkit-scrollbar-thumb:hover { background: rgba(117, 102, 255, 0.45); }
/* 3. TYPOGRAPHY */
.brand-title { font-size: var(--fs-24); font-weight: 650; letter-spacing: -0.02em; line-height: 1.2; color: var(--text-1); margin: 0; }
.section-label { color: var(--text-3); font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600; margin: var(--sp-12) 0 var(--sp-4); }
div[data-testid="stChatMessageContent"] { font-size: var(--fs-15); line-height: 1.7; overflow-wrap: break-word; word-break: break-word; min-width: 0; max-width: 100%; }
div[data-testid="stChatMessageContent"] p { margin: 0 0 var(--sp-12); }
div[data-testid="stChatMessageContent"] p:last-child { margin-bottom: 0; }
div[data-testid="stChatMessageContent"] h1, div[data-testid="stChatMessageContent"] h2, div[data-testid="stChatMessageContent"] h3, div[data-testid="stChatMessageContent"] h4 { font-weight: 650; letter-spacing: -0.015em; color: var(--text-1); margin: var(--sp-20) 0 var(--sp-8); line-height: 1.35; }
div[data-testid="stChatMessageContent"] h1:first-child, div[data-testid="stChatMessageContent"] h2:first-child, div[data-testid="stChatMessageContent"] h3:first-child { margin-top: 0; }
div[data-testid="stChatMessageContent"] h1 { font-size: var(--fs-20); }
div[data-testid="stChatMessageContent"] h2 { font-size: var(--fs-18); }
div[data-testid="stChatMessageContent"] h3 { font-size: var(--fs-16); }
div[data-testid="stChatMessageContent"] h4 { font-size: var(--fs-15); }
div[data-testid="stChatMessageContent"] ul, div[data-testid="stChatMessageContent"] ol { margin: 0 0 var(--sp-12); padding-left: 22px; }
div[data-testid="stChatMessageContent"] li { margin: 5px 0; line-height: 1.65; }
div[data-testid="stChatMessageContent"] li::marker { color: var(--text-3); }
div[data-testid="stChatMessageContent"] a { color: var(--accent-hover); text-decoration: none; overflow-wrap: anywhere; }
div[data-testid="stChatMessageContent"] a:hover { text-decoration: underline; }
div[data-testid="stChatMessageContent"] hr { border: none; border-top: 1px solid var(--border); margin: var(--sp-16) 0; }
div[data-testid="stChatMessageContent"] blockquote { margin: 0 0 var(--sp-12); padding: var(--sp-8) var(--sp-16); border-left: 2px solid var(--border-strong); border-radius: 0 var(--r-sm) var(--r-sm) 0; background: var(--bg-1); color: var(--text-2); }
div[data-testid="stChatMessageContent"] blockquote p { margin-bottom: 6px; }
div[data-testid="stChatMessageContent"] table { width: 100%; display: block; overflow-x: auto; border-collapse: collapse; font-size: var(--fs-14); margin: 0 0 var(--sp-12); }
div[data-testid="stChatMessageContent"] th, div[data-testid="stChatMessageContent"] td { text-align: left; padding: var(--sp-8) var(--sp-12); border-bottom: 1px solid var(--border); white-space: nowrap; }
div[data-testid="stChatMessageContent"] td { white-space: normal; color: var(--text-1); }
div[data-testid="stChatMessageContent"] th { color: var(--text-3); font-size: var(--fs-12); font-weight: 650; text-transform: uppercase; letter-spacing: 0.06em; }
div[data-testid="stChatMessageContent"] tr:hover td { background: var(--bg-2); }
div[data-testid="stChatMessageContent"] code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; background: var(--bg-2); border: 1px solid var(--border); border-radius: 6px; padding: 0.12rem 0.38rem; font-size: 13px; color: var(--text-1); overflow-wrap: anywhere; }
div[data-testid="stChatMessageContent"] pre { background: var(--bg-1); border: 1px solid var(--border); border-radius: var(--r-md); padding: var(--sp-16); margin: 0 0 var(--sp-12); overflow-x: auto; line-height: 1.6; box-shadow: var(--shadow-subtle); }
div[data-testid="stChatMessageContent"] pre code { background: transparent; border: none; border-radius: 0; padding: 0; font-size: 13px; line-height: 1.65; }
div[data-testid="stImage"] { max-width: 340px; }
div[data-testid="stImage"] img { max-width: 340px; width: 100%; border-radius: var(--r-md); border: 1px solid var(--border); box-shadow: var(--shadow-subtle); }
/* 4. BUTTONS */
.poka-btn-primary { background: var(--accent); color: var(--text-1); border: 1px solid var(--accent); border-radius: var(--r-sm); }
.poka-btn-secondary { background: transparent; color: var(--text-1); border: 1px solid transparent; border-radius: var(--r-sm); }
.poka-icon-btn { width: 36px; height: 36px; border-radius: var(--r-pill); display: inline-flex; align-items: center; justify-content: center; }
.poka-icon-btn svg { width: 18px; height: 18px; display: block; }
div[data-testid="stBaseButton-secondary"] > button, .stButton > button { transition: background-color var(--dur) var(--ease), border-color var(--dur) var(--ease), color var(--dur) var(--ease), transform var(--dur) var(--ease), box-shadow var(--dur) var(--ease); }
div[data-testid="stBaseButton-secondary"] > button:active, .stButton > button:active { transform: scale(0.97); }
/* 5. SIDEBAR INPUTS */
section[data-testid="stSidebar"] div[data-testid="stTextInput"] input { background: var(--bg-2); border: 1px solid var(--border); border-radius: 10px; color: var(--text-1); font-size: var(--fs-14); min-height: 38px; transition: border-color var(--dur) var(--ease), box-shadow var(--dur) var(--ease); }
section[data-testid="stSidebar"] div[data-testid="stTextInput"] input::placeholder { color: var(--text-3); opacity: 1; }
section[data-testid="stSidebar"] div[data-testid="stTextInput"] input:focus { border-color: var(--border-strong); box-shadow: 0 0 0 3px var(--accent-wash); outline: none; }
section[data-testid="stSidebar"] div[data-testid="stTextArea"] textarea { background: var(--bg-2); border: 1px solid var(--border); border-radius: 10px; color: var(--text-1); font-size: var(--fs-14); line-height: 1.6; transition: border-color var(--dur) var(--ease), box-shadow var(--dur) var(--ease); }
section[data-testid="stSidebar"] div[data-testid="stTextArea"] textarea:focus { border-color: var(--border-strong); box-shadow: 0 0 0 3px var(--accent-wash); outline: none; }
/* 6. CARDS + DOWNLOADS */
.stats-box { background: transparent; border: none; border-radius: 0; padding: 2px; }
div[data-testid="stDownloadButton"] > button { background: var(--bg-2); color: var(--text-1); border: 1px solid var(--border); border-radius: 10px; width: 100%; }
div[data-testid="stDownloadButton"] > button:hover { background: var(--bg-3); border-color: var(--border-strong); color: var(--text-1); }
div[data-testid="stToast"] { background: var(--bg-2); border: 1px solid var(--border); border-radius: 10px; color: var(--text-1); box-shadow: var(--shadow-menu); }
/* 7. MESSAGES */
div[data-testid="stChatMessage"] { background: transparent; border: none; padding: var(--sp-8) 0; margin: 0 0 var(--sp-24); position: relative; }
div[data-testid="stChatMessage"]:last-child { margin-bottom: 0; }
@keyframes poka-fade { from { opacity: 0; } to { opacity: 1; } }
.poka-assistant-id { display: flex; align-items: center; gap: var(--sp-8); font-size: var(--fs-14); font-weight: 650; letter-spacing: -0.01em; color: var(--text-1); margin: 0 0 6px 2px; }
.poka-assistant-mark { width: 22px; height: 22px; border-radius: var(--r-pill); background: var(--accent-wash); border: 1px solid var(--border); display: inline-flex; align-items: center; justify-content: center; color: var(--accent-hover); }
.poka-assistant-mark svg { display: block; fill: currentColor; }
.poka-meta { display: flex; align-items: center; justify-content: space-between; gap: var(--sp-8); margin: 6px 0 0 2px; min-height: 22px; }
.poka-time { font-size: var(--fs-12); color: var(--text-3); font-variant-numeric: tabular-nums; white-space: nowrap; letter-spacing: 0.01em; }
.poka-copy { position: static; display: inline-block; flex-shrink: 0; background: transparent; color: var(--text-3); border: 1px solid transparent; border-radius: var(--r-pill); font-size: 11px; font-weight: 600; letter-spacing: 0.02em; padding: 4px 11px; margin: 0; cursor: pointer; opacity: 0; min-width: 58px; text-align: center; transition: opacity var(--dur) var(--ease), background-color var(--dur) var(--ease), color var(--dur) var(--ease), border-color var(--dur) var(--ease); z-index: 3; }
.poka-copy:hover { color: var(--text-1); background: var(--bg-2); border-color: var(--border); }
.poka-copy:active { transform: scale(0.95); }
.poka-copy:focus-visible { opacity: 1; outline: 2px solid var(--accent); outline-offset: 2px; }
div[data-testid="stChatMessage"]:hover .poka-copy { opacity: 1; }
@media (hover: none) { .poka-copy { opacity: 1; } }
div[data-testid="stChatMessage"] [data-testid="stHorizontalBlock"] { gap: var(--sp-8) !important; }
div[class*="st-key-edit-"] { display: flex; justify-content: flex-end; }
div[class*="st-key-edit-"] div[data-testid="stBaseButton-secondary"] > button, div[class*="st-key-edit-"] .stButton > button { width: auto; background: transparent; border: 1px solid transparent; color: var(--text-3); font-size: var(--fs-12); font-weight: 600; border-radius: var(--r-pill); padding: 4px 14px; text-align: center; min-height: 30px; white-space: nowrap; }
div[class*="st-key-edit-"] div[data-testid="stBaseButton-secondary"] > button:hover, div[class*="st-key-edit-"] .stButton > button:hover { color: var(--text-1); border-color: var(--border); background: var(--bg-2); transform: none; }
.st-key-retry-main button { width: auto !important; background: transparent !important; border: 1px solid var(--border) !important; color: var(--text-1) !important; border-radius: var(--r-pill) !important; font-size: 13px !important; font-weight: 600 !important; padding: 7px 20px !important; min-height: 36px !important; }
.st-key-retry-main button:hover { background: var(--bg-2) !important; border-color: var(--border-strong) !important; }
section[data-testid="stMain"] div[data-testid="stDownloadButton"] > button { width: auto; max-width: 100%; min-height: 36px; font-size: var(--fs-14); font-weight: 600; padding: 8px 16px; border-radius: var(--r-pill); }
section[data-testid="stMain"] div[data-testid="stAlert"] { background: rgba(239, 68, 68, 0.07); border: 1px solid rgba(239, 68, 68, 0.28); border-radius: var(--r-md); color: var(--text-1); font-size: var(--fs-14); }
section[data-testid="stMain"] div[data-testid="stAlert"] p { margin: 0; line-height: 1.6; }
section[data-testid="stMain"] div[data-testid="stAlert"] [data-testid="stAlertContentError"] { color: var(--text-1); }
.poka-error { background: rgba(239, 68, 68, 0.07); border: 1px solid rgba(239, 68, 68, 0.28); border-radius: var(--r-md); padding: var(--sp-12) var(--sp-16); max-width: 100%; }
.poka-error-title { font-size: var(--fs-14); font-weight: 650; color: #FCA5A5; margin-bottom: var(--sp-4); }
.poka-error-detail { font-size: 13px; line-height: 1.6; color: var(--text-2); overflow-wrap: break-word; }
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]) div[data-testid="stChatMessageAvatarUser"] { display: none; }
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]) div[data-testid="stChatMessageContent"] { background: var(--bg-2); color: var(--text-1); padding: var(--sp-8) var(--sp-12); border-radius: var(--r-md) var(--r-md) var(--sp-4) var(--r-md); border: 1px solid var(--border); box-shadow: none; margin-left: auto; max-width: min(70%, 480px); animation: poka-fade var(--dur) var(--ease); font-size: var(--fs-15); line-height: 1.65; transition: border-color var(--dur) var(--ease); }
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]):hover div[data-testid="stChatMessageContent"] { border-color: var(--border-strong); }
div[data-testid="stChatMessageAvatarAssistant"] { display: none; }
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarAssistant"]) div[data-testid="stChatMessageContent"] { background: transparent; color: var(--text-1); padding: 6px 2px var(--sp-8); border-radius: 0; border: none; box-shadow: none; animation: poka-fade var(--dur) var(--ease); font-size: var(--fs-15); line-height: 1.7; max-width: 100%; }
.typing-indicator { display: flex; gap: 6px; padding: var(--sp-16) 2px; align-items: center; }
.typing-indicator span:not(.typing-label) { width: 6px; height: 6px; background: var(--text-3); border-radius: 50%; opacity: 0.45; animation: poka-pulse 1.2s infinite var(--ease); }
.typing-indicator span:nth-child(2) { animation-delay: 0.15s; }
.typing-indicator span:nth-child(3) { animation-delay: 0.3s; }
.typing-label { font-size: var(--fs-12); font-weight: 600; letter-spacing: 0.02em; color: var(--text-3); margin-left: 2px; }
@keyframes poka-pulse { 0%, 100% { opacity: 0.3; } 50% { opacity: 0.9; } }
mark.search-hit { background: var(--accent-wash); color: inherit; border-radius: 3px; padding: 0 2px; box-decoration-break: clone; -webkit-box-decoration-break: clone; }
.poka-sources { margin: 2px 0 var(--sp-8) 2px; }
.poka-sources-head { color: var(--text-3); font-size: 11px; text-transform: uppercase; letter-spacing: 0.09em; font-weight: 650; margin: 0 0 var(--sp-4); }
.poka-source { font-size: 13px; line-height: 1.6; color: var(--text-2); margin: 0 0 var(--sp-4); overflow-wrap: anywhere; }
.poka-source-n { color: var(--text-3); font-variant-numeric: tabular-nums; margin-right: var(--sp-4); }
.poka-sources a { color: var(--text-1); font-weight: 600; text-decoration: none; }
.poka-sources a:hover { color: var(--accent-hover); text-decoration: underline; }
.poka-sources a:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.poka-sources a::after { content: "↗"; font-size: 11px; font-weight: 400; color: var(--text-3); margin-left: 3px; }
.poka-source-d { color: var(--text-3); font-size: var(--fs-12); }
/* 8. SIDEBAR */
section[data-testid="stSidebar"] { background: var(--bg-1) !important; border-right: 1px solid var(--border); width: 264px; }
section[data-testid="stSidebar"] .block-container { padding: var(--sp-12) var(--sp-12) var(--sp-16); }
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: var(--sp-4); }
section[data-testid="stSidebar"] div[data-testid="stBaseButton-primary"] > button { background: var(--accent); color: var(--text-1); border: 1px solid var(--accent); border-radius: 10px; width: 100%; font-weight: 650; transition: background-color var(--dur) var(--ease), transform var(--dur) var(--ease), box-shadow var(--dur) var(--ease); }
section[data-testid="stSidebar"] div[data-testid="stBaseButton-primary"] > button:hover { background: var(--accent-hover); border-color: var(--accent-hover); color: var(--text-1); transform: translateY(-1px); box-shadow: var(--shadow-subtle); }
section[data-testid="stSidebar"] div[data-testid="stBaseButton-primary"] > button:active { background: var(--accent-pressed); transform: scale(0.98); box-shadow: none; }
section[data-testid="stSidebar"] div[data-testid="stBaseButton-secondary"] > button { background: transparent; border: 1px solid transparent; border-radius: var(--r-sm); color: var(--text-1); text-align: left; width: 100%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
section[data-testid="stSidebar"] div[data-testid="stBaseButton-secondary"] > button:hover { background: var(--bg-3); border-color: var(--border); color: var(--text-1); }
.poka-brand { display: flex; align-items: center; gap: 10px; padding: 2px 4px 0; }
.poka-mark { width: 30px; height: 30px; min-width: 30px; border-radius: 9px; background: var(--accent-wash); border: 1px solid var(--border); display: inline-flex; align-items: center; justify-content: center; color: var(--accent-hover); box-shadow: var(--shadow-subtle); }
.poka-mark svg { width: 16px; height: 16px; display: block; fill: currentColor; }
.poka-brand-text { display: flex; flex-direction: column; line-height: 1.25; min-width: 0; }
.poka-word { font-size: var(--fs-15); font-weight: 650; letter-spacing: -0.01em; color: var(--text-1); }
.poka-sub { font-size: var(--fs-12); color: var(--text-3); letter-spacing: 0.01em; }
.poka-model { display: flex; align-items: center; gap: var(--sp-8); margin-top: var(--sp-8); padding: 6px 10px; min-width: 0; background: var(--bg-2); border: 1px solid var(--border); border-radius: var(--r-pill); width: fit-content; max-width: 100%; }
.poka-model-name { font-size: var(--fs-12); font-weight: 600; color: var(--text-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; letter-spacing: 0.01em; }
.poka-dot { width: 7px; height: 7px; min-width: 7px; border-radius: var(--r-pill); display: inline-block; }
.poka-dot-online { background: var(--success); }
.poka-dot-offline { background: var(--danger); }
.poka-footer { margin-top: var(--sp-4); padding: 0 2px var(--sp-4); background: transparent; border: none; width: auto; }
.poka-divider { height: 1px; background: var(--border); margin: var(--sp-12) 0; opacity: 0.8; }
section[data-testid="stSidebar"] [data-testid="stHorizontalBlock"]:has([class*="st-key-mode-"]) { gap: 0 !important; background: var(--bg-2); border: 1px solid var(--border); border-radius: 10px; padding: 3px; }
div[class*="st-key-mode-"] button { width: 100% !important; min-height: 34px !important; font-size: 13px !important; font-weight: 650 !important; letter-spacing: 0.01em !important; background: transparent !important; border: 1px solid transparent !important; border-radius: 7px !important; color: var(--text-3) !important; user-select: none !important; -webkit-user-select: none !important; }
div[class*="st-key-mode-"] button:hover:not(:disabled) { background: var(--bg-3) !important; color: var(--text-1) !important; }
div[class*="st-key-mode-"] button:disabled { background: var(--bg-3) !important; border-color: var(--border) !important; color: var(--text-1) !important; opacity: 1 !important; cursor: default !important; box-shadow: var(--shadow-subtle) !important; }
.st-key-new-chat button { min-height: 40px !important; border-radius: 10px !important; font-size: var(--fs-14) !important; font-weight: 650 !important; letter-spacing: 0.005em !important; }
.poka-match { color: var(--text-3); font-size: var(--fs-12); font-variant-numeric: tabular-nums; margin: var(--sp-4) 2px 0; }
.poka-empty { color: var(--text-3); font-size: var(--fs-12); line-height: 1.5; margin: 2px; }
.poka-card-sub { color: var(--text-2); font-size: var(--fs-12); font-weight: 650; letter-spacing: 0.04em; text-transform: uppercase; margin: 0 0 var(--sp-8); }
/* 14b. MEMORY VAULT — compact scannable rows */
.poka-mem-row { padding: 2px 0 var(--sp-8); min-width: 0; }
.poka-mem-head { display: flex; align-items: center; gap: 6px; margin-bottom: 2px; min-width: 0; }
.poka-mem-type { font-size: 11px; font-weight: 650; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-2); white-space: nowrap; }
.poka-mem-src { font-size: 11px; color: var(--text-3); white-space: nowrap; }
.poka-mem-src::before { content: "·"; margin-right: 6px; color: var(--border-strong); }
.poka-mem-val { font-size: 13px; font-weight: 500; color: var(--text-1); line-height: 1.5; overflow-wrap: anywhere; }
.poka-mem-date { font-size: 11px; color: var(--text-3); margin-top: 1px; }
div[class*="st-key-forget-fact-"] button { min-width: 28px !important; width: 28px !important; height: 28px !important; min-height: 28px !important; border-radius: var(--r-pill) !important; background: transparent !important; border: 1px solid transparent !important; color: var(--text-3) !important; font-size: var(--fs-16) !important; font-weight: 400 !important; line-height: 1 !important; padding: 0 0 2px !important; }
div[class*="st-key-forget-fact-"] button:hover { color: var(--danger) !important; background: rgba(239, 68, 68, 0.1) !important; border-color: rgba(239, 68, 68, 0.3) !important; transform: none !important; }
section[data-testid="stSidebar"] div[data-testid="stCaptionContainer"] { color: var(--text-3); font-size: var(--fs-12); line-height: 1.5; }
section[data-testid="stSidebar"] div[data-testid="column"] .stButton > button { padding-top: var(--sp-8); padding-bottom: var(--sp-8); font-size: var(--fs-14); }
div[class*="st-key-rename-"] button { color: var(--text-3) !important; opacity: 0.55; }
div[class*="st-key-rename-"] button:hover { opacity: 1; color: var(--text-1) !important; }
@media (hover: none) { div[class*="st-key-rename-"] button { opacity: 1; } }
/* Projects — quiet rows; the active (disabled) row is unmistakable by
   surface + weight + accent edge, never color alone. */
.st-key-project-personal button:disabled,
div[class*="st-key-project-"] button:disabled {
    background: var(--accent-wash) !important;
    border: 1px solid rgba(117, 102, 255, 0.35) !important;
    box-shadow: inset 2px 0 0 var(--accent) !important;
    color: var(--text-1) !important;
    font-weight: 650 !important;
    opacity: 1 !important;
    cursor: default !important;
}
.st-key-project-create button {
    background: transparent !important;
    border: 1px solid transparent !important;
    color: var(--text-2) !important;
    font-size: 18px !important;
    font-weight: 400 !important;
    min-height: 34px !important;
    border-radius: var(--r-sm) !important;
}
.st-key-project-create button:hover {
    background: var(--bg-3) !important;
    border-color: var(--border) !important;
    color: var(--text-1) !important;
}
div[class*="st-key-project-pencil-"] button { color: var(--text-3) !important; opacity: 0.55; }
div[class*="st-key-project-pencil-"] button:hover { opacity: 1; color: var(--text-1) !important; }
@media (hover: none) { div[class*="st-key-project-pencil-"] button { opacity: 1; } }
div[class*="st-key-project-archive-"] button {
    background: transparent !important;
    border: 1px solid transparent !important;
    color: var(--text-2) !important;
    font-weight: 600 !important;
}
div[class*="st-key-project-archive-"] button:hover {
    background: rgba(239, 68, 68, 0.1) !important;
    border-color: rgba(239, 68, 68, 0.3) !important;
    color: var(--danger) !important;
    transform: none !important;
    box-shadow: none !important;
}
div[class*="st-key-project-archive-dismiss"] button {
    background: transparent !important;
    border: 1px solid transparent !important;
    color: var(--text-2) !important;
}
div[class*="st-key-project-archive-dismiss"] button:hover {
    background: var(--bg-3) !important;
    border-color: var(--border) !important;
    color: var(--text-1) !important;
}
/* Project rows carry folder/home marks aligned with row text. Action
   widgets (create, pencil, rename, archive, context) are excluded. */
div[class*="st-key-project-"]:not([class*="create"]):not([class*="pencil"]):not([class*="rename"]):not([class*="archive"]):not([class*="context"]) button {
    padding-left: 32px !important;
    position: relative !important;
}
div[class*="st-key-project-"]:not([class*="create"]):not([class*="pencil"]):not([class*="rename"]):not([class*="archive"]):not([class*="context"]) button::before {
    content: "" !important;
    position: absolute !important;
    left: 10px !important;
    top: 50% !important;
    translate: 0 -50% !important;
    width: 15px !important;
    height: 15px !important;
    background-repeat: no-repeat !important;
    background-position: center !important;
    background-size: contain !important;
    opacity: 0.85 !important;
}
.st-key-project-personal button::before {
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='currentColor' stroke-width='1.4' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M3 8.5L8 4l5 4.5M5.5 7.5V13h5V7.5'/%3E%3C/svg%3E") !important;
}
div[class*="st-key-project-"]:not([class*="create"]):not([class*="pencil"]):not([class*="rename"]):not([class*="archive"]):not([class*="context"]):not(.st-key-project-personal) button::before {
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='currentColor' stroke-width='1.4' stroke-linejoin='round'%3E%3Cpath d='M2 4.5c0-.8.7-1.5 1.5-1.5H7l1.5 2H13c.8 0 1.5.7 1.5 1.5V12c0 .8-.7 1.5-1.5 1.5h-9.5C2.7 13.5 2 12.8 2 12z'/%3E%3C/svg%3E") !important;
}
/* Save context is a primary action within the project block. */
.st-key-project-context-save button {
    background: var(--accent) !important;
    border: 1px solid var(--accent) !important;
    color: var(--text-1) !important;
    font-weight: 650 !important;
    border-radius: 10px !important;
    width: 100% !important;
}
.st-key-project-context-save button:hover {
    background: var(--accent-hover) !important;
    border-color: var(--accent-hover) !important;
    color: var(--text-1) !important;
}
.st-key-project-context-save button:active {
    background: var(--accent-pressed) !important;
    border-color: var(--accent-pressed) !important;
}
section[data-testid="stSidebar"] div[data-testid="stVerticalBlockBorderWrapper"] { background: var(--bg-2); border: 1px solid var(--border); border-radius: var(--r-md); padding: var(--sp-12); box-shadow: var(--shadow-subtle); }
div[class*="st-key-rename-save-"] button { background: var(--accent-wash) !important; border: 1px solid rgba(117, 102, 255, 0.35) !important; color: var(--text-1) !important; }
div[class*="st-key-rename-save-"] button:hover { background: var(--accent) !important; border-color: var(--accent) !important; }
.poka-file-row { display: flex; align-items: center; gap: var(--sp-8); padding: 7px var(--sp-8); min-width: 0; border-radius: var(--r-sm); transition: background-color var(--dur) var(--ease); }
.poka-file-row:hover { background: var(--bg-3); }
.poka-file-icon { color: var(--text-3); display: inline-flex; min-width: 14px; }
.poka-file-icon svg { display: block; }
.poka-file-name { font-size: 13px; font-weight: 500; color: var(--text-1); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; overflow-wrap: anywhere; }
.poka-file-sub { font-size: var(--fs-12); color: var(--text-3); margin: 0 0 var(--sp-8) 22px; font-variant-numeric: tabular-nums; }
/* 14c. ARTIFACTS — compact rows reusing file-row geometry */
.poka-art { display: flex; align-items: flex-start; gap: var(--sp-8); background: transparent; border: none; border-bottom: 1px solid var(--border); border-radius: 0; padding: 7px 2px; margin: 0; min-width: 0; }
.poka-art-icon { color: var(--text-3); display: inline-flex; min-width: 14px; margin-top: 2px; }
.poka-art-icon svg { display: block; }
.poka-art-text { display: flex; flex-direction: column; gap: 1px; min-width: 0; flex: 1 1 auto; }
.poka-art-name { font-size: 13px; font-weight: 600; color: var(--text-1); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; overflow-wrap: anywhere; }
.poka-art-sub { font-size: var(--fs-12); color: var(--text-3); font-variant-numeric: tabular-nums; }
.poka-art-expired { opacity: 0.65; }
.poka-art-expired .poka-art-sub { color: var(--warning); }
section[data-testid="stSidebar"] div[data-testid="stDownloadButton"] > button { min-height: 32px; font-size: var(--fs-12); font-weight: 600; padding: 6px 10px; border-radius: var(--r-sm); }
.poka-stat-row { display: flex; justify-content: space-between; align-items: center; gap: var(--sp-12); margin-bottom: var(--sp-8); }
.poka-stat-row:last-child { margin-bottom: 0; }
.poka-stat-key { color: var(--text-2); font-size: 13px; }
.poka-stat-val { color: var(--text-1); font-weight: 650; font-size: 13px; font-variant-numeric: tabular-nums; }
.poka-stat-active { color: var(--text-1); font-weight: 600; font-size: var(--fs-12); max-width: 140px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.st-key-clean-files button { background: transparent !important; border: 1px solid transparent !important; color: var(--text-2) !important; font-weight: 600 !important; }
.st-key-clean-files button:hover { background: rgba(239, 68, 68, 0.1) !important; border-color: rgba(239, 68, 68, 0.3) !important; color: var(--danger) !important; transform: none !important; box-shadow: none !important; }
/* 9. COMPOSER — unified command bar (shell + anchor merged; BaseWeb reset below is load-bearing, keep every !important) */
.st-key-composer { position: sticky !important; bottom: var(--sp-16) !important; width: min(600px, calc(100% - var(--sp-32))) !important; margin-left: auto !important; margin-right: auto !important; margin-top: var(--sp-8) !important; background: var(--bg-1) !important; background-color: var(--bg-1) !important; border: 1px solid var(--border) !important; border-radius: 24px !important; padding: var(--sp-8) 10px !important; box-sizing: border-box !important; z-index: 50 !important; box-shadow: var(--shadow-composer) !important; transition: border-color var(--dur) var(--ease), box-shadow var(--dur) var(--ease) !important; anchor-name: --poka-composer; }
.st-key-composer:focus-within { border-color: var(--border-strong) !important; box-shadow: var(--shadow-composer), 0 0 0 3px var(--accent-wash) !important; }
.st-key-composer [data-testid="stVerticalBlock"] { gap: 0 !important; }
.st-key-composer [data-testid="stHorizontalBlock"] { width: 100% !important; margin: 0 !important; padding: 0 !important; gap: 6px !important; align-items: center !important; }
.st-key-composer [data-testid="column"] { min-width: 0 !important; padding: 0 !important; margin: 0 !important; display: flex !important; align-items: center !important; justify-content: center !important; }
.st-key-composer [data-testid="stTextInput"] { width: 100% !important; margin: 0 !important; padding: 0 !important; }
.st-key-composer [data-testid="stTextInput"] label { display: none !important; }
.st-key-composer div[data-testid="InputInstructions"] { display: none !important; }
.st-key-composer [data-testid="stTextInput"] div, .st-key-composer [data-testid="stTextInput"] span, .st-key-composer [data-testid="stTextInput"] input, .st-key-composer [data-testid="stTextInput"] [data-baseweb], .st-key-composer [data-testid="stTextInput"] [data-baseweb="input"], .st-key-composer [data-testid="stTextInput"] [data-baseweb="base-input"] { background: transparent !important; background-color: transparent !important; background-image: none !important; border: 0 !important; border-width: 0 !important; border-style: none !important; border-color: transparent !important; border-radius: 0 !important; outline: none !important; box-shadow: none !important; }
.st-key-composer [data-testid="stTextInput"] input { -webkit-appearance: none !important; appearance: none !important; width: 100% !important; color: var(--text-1) !important; -webkit-text-fill-color: var(--text-1) !important; font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif !important; font-size: var(--fs-15) !important; font-weight: 400 !important; line-height: 1.5 !important; padding: var(--sp-8) 10px !important; margin: 0 !important; min-height: 38px !important; height: 38px !important; caret-color: var(--accent-hover) !important; }
.st-key-composer [data-testid="stTextInput"] input::placeholder { color: var(--text-3) !important; -webkit-text-fill-color: var(--text-3) !important; opacity: 1 !important; }
.st-key-composer [data-testid="stTextInput"] *:focus, .st-key-composer [data-testid="stTextInput"] *:focus-visible, .st-key-composer [data-testid="stTextInput"] *:focus-within { background: transparent !important; background-color: transparent !important; border: 0 !important; box-shadow: none !important; outline: none !important; }
.st-key-composer button { width: 34px !important; height: 34px !important; min-width: 34px !important; max-width: 34px !important; padding: 0 !important; margin: 0 !important; border-radius: var(--r-pill) !important; display: flex !important; align-items: center !important; justify-content: center !important; font-size: 0 !important; line-height: 1 !important; box-shadow: none !important; transition: background-color var(--dur) var(--ease), border-color var(--dur) var(--ease), color var(--dur) var(--ease), transform var(--dur) var(--ease), box-shadow var(--dur) var(--ease), opacity var(--dur) var(--ease) !important; }
.st-key-composer button::after { content: "" !important; width: 18px !important; height: 18px !important; flex-shrink: 0 !important; background-repeat: no-repeat !important; background-position: center !important; background-size: contain !important; }
.st-key-composer button:disabled { opacity: 0.4 !important; cursor: not-allowed !important; transform: none !important; box-shadow: none !important; }
.st-key-composer [data-testid="column"]:first-child button { background: transparent !important; background-color: transparent !important; border: 1px solid transparent !important; color: var(--text-2) !important; }
.st-key-composer [data-testid="column"]:first-child button::after { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='%23A1A1AA' stroke-width='1.8' stroke-linecap='round'%3E%3Cpath d='M8 3v10M3 8h10'/%3E%3C/svg%3E") !important; }
.st-key-composer [data-testid="column"]:first-child button:hover { background: var(--bg-3) !important; background-color: var(--bg-3) !important; border-color: var(--border) !important; color: var(--text-1) !important; }
.st-key-composer [data-testid="column"]:first-child button:hover::after { filter: brightness(1.35) !important; }
.st-key-composer [data-testid="column"]:first-child button:active { transform: scale(0.94) !important; }
.st-key-composer [data-testid="column"]:last-child button { background: var(--accent) !important; background-color: var(--accent) !important; border: 1px solid var(--accent) !important; color: var(--text-1) !important; }
.st-key-composer [data-testid="column"]:last-child button::after { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='white' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M8 13.5v-11M3.5 7.5L8 3l4.5 4.5'/%3E%3C/svg%3E") !important; }
.st-key-composer [data-testid="column"]:last-child button:hover { background: var(--accent-hover) !important; background-color: var(--accent-hover) !important; border-color: var(--accent-hover) !important; color: var(--text-1) !important; box-shadow: var(--shadow-subtle) !important; transform: translateY(-1px) !important; }
.st-key-composer [data-testid="column"]:last-child button:active { background: var(--accent-pressed) !important; background-color: var(--accent-pressed) !important; border-color: var(--accent-pressed) !important; transform: scale(0.94) !important; box-shadow: none !important; }
/* 10. ATTACHMENTS — command menu + chips */
.st-key-composer_plus { anchor-name: --poka-plus; }
@keyframes poka-menu-in { from { opacity: 0; translate: 0 calc(-100% - 6px); } to { opacity: 1; translate: 0 calc(-100% - 10px); } }
.st-key-attachment-menu { position: fixed !important; position-anchor: --poka-plus !important; left: anchor(left) !important; top: anchor(top) !important; bottom: auto !important; translate: 0 calc(-100% - 10px) !important; animation: poka-menu-in 140ms var(--ease); width: 248px !important; max-width: calc(100vw - var(--sp-32)) !important; max-height: calc(100vh - 200px) !important; overflow-y: auto !important; background: var(--bg-2) !important; border: 1px solid var(--border) !important; border-radius: var(--r-md) !important; padding: var(--sp-8) !important; z-index: 100 !important; box-shadow: var(--shadow-menu) !important; }
@supports not (position-anchor: --poka-composer) { .st-key-attachment-menu { left: max(16px, calc(50% - 24rem)) !important; top: auto !important; bottom: 96px !important; translate: none !important; animation: none !important; max-width: 300px !important; } }
.st-key-attachment-menu button { width: 100% !important; min-height: 44px !important; border: none !important; border-radius: 10px !important; background: transparent !important; color: var(--text-1) !important; text-align: left !important; padding: 10px 12px 10px 40px !important; font-size: var(--fs-14) !important; font-weight: 500 !important; box-shadow: none !important; position: relative !important; overflow: hidden !important; text-overflow: ellipsis !important; white-space: nowrap !important; }
.st-key-attachment-menu button:hover { background: var(--bg-3) !important; color: var(--text-1) !important; }
.st-key-attachment-menu button::before { content: "" !important; position: absolute !important; left: 12px !important; top: 50% !important; translate: 0 -50% !important; width: 18px !important; height: 18px !important; background-repeat: no-repeat !important; background-position: center !important; background-size: contain !important; opacity: 0.9 !important; }
.st-key-menu-files button::before { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='%23A1A1AA' stroke-width='1.4' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M8 11V3M4.5 6.5L8 3l3.5 3.5'/%3E%3Cpath d='M2.5 11.5v2a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1v-2'/%3E%3C/svg%3E") !important; }
div[class*="st-key-recent-pdf-"] button::before { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='%23A1A1AA' stroke-width='1.3'%3E%3Cpath d='M3 1h5l4 4v10H3z'/%3E%3Cpath d='M8 1v4h4'/%3E%3C/svg%3E") !important; }
div[class*="st-key-recent-csv-"] button::before { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='%23A1A1AA' stroke-width='1.3'%3E%3Crect x='2' y='2.5' width='12' height='11' rx='1.5'/%3E%3Cpath d='M2 6.5h12M7 6.5v7'/%3E%3C/svg%3E") !important; }
div[class*="st-key-recent-img-"] button::before { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='%23A1A1AA' stroke-width='1.3'%3E%3Crect x='2' y='2.5' width='12' height='11' rx='1.5'/%3E%3Ccircle cx='5.5' cy='6.5' r='1.3' fill='%23A1A1AA' stroke='none'/%3E%3Cpath d='M2.5 12.5l3.5-3.5 2.5 2.5 2-2 3 3'/%3E%3C/svg%3E") !important; }
.st-key-menu-camera button::before { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='%23A1A1AA' stroke-width='1.4'%3E%3Crect x='1.5' y='4' width='13' height='9' rx='2'/%3E%3Ccircle cx='8' cy='8.5' r='2.5'/%3E%3Cpath d='M5.5 4l1-1.5h3l1 1.5'/%3E%3C/svg%3E") !important; }
.st-key-menu-search button::before { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='%23A1A1AA' stroke-width='1.4'%3E%3Ccircle cx='8' cy='8' r='6'/%3E%3Cpath d='M2 8h12M8 2c-3.5 3.5-3.5 8.5 0 12M8 2c3.5 3.5 3.5 8.5 0 12'/%3E%3C/svg%3E") !important; }
.poka-menu-head { color: var(--text-1); font-size: 13px; font-weight: 650; letter-spacing: 0.005em; margin: 6px 6px 2px; }
.poka-menu-sub { color: var(--text-3); font-size: var(--fs-12); line-height: 1.5; margin: 2px 6px var(--sp-8) 40px; }
.st-key-attachment-menu div[data-testid="stFileUploader"], .st-key-attachment-menu div[data-testid="stCameraInput"] { margin-top: var(--sp-4) !important; max-width: 100% !important; padding: 6px !important; }
.st-key-attachment-menu div[data-testid="stFileUploader"] button { padding: 6px 10px !important; min-height: 32px !important; }
.poka-chips { display: flex; flex-wrap: wrap; gap: var(--sp-8); width: min(600px, 100%); margin: 0 auto var(--sp-8); }
.poka-chip { display: inline-flex; align-items: center; gap: var(--sp-8); background: var(--bg-2); border: 1px solid var(--border); border-radius: 10px; padding: 8px var(--sp-12); font-size: 13px; font-weight: 500; color: var(--text-1); max-width: 100%; min-width: 0; box-shadow: var(--shadow-subtle); }
.poka-chip-icon { color: var(--text-3); display: inline-flex; min-width: 14px; }
.poka-chip-icon svg { display: block; }
.poka-chip-name { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; overflow-wrap: anywhere; }
div[class*="st-key-rm-attach"] button { width: 30px !important; height: 30px !important; min-width: 30px !important; max-width: 30px !important; border-radius: var(--r-pill) !important; background: var(--bg-2) !important; border: 1px solid var(--border) !important; color: var(--text-2) !important; font-size: 0 !important; line-height: 1 !important; padding: 0 !important; display: flex !important; align-items: center !important; justify-content: center !important; }
div[class*="st-key-rm-attach"] button::after { content: "" !important; width: 14px !important; height: 14px !important; background-repeat: no-repeat !important; background-position: center !important; background-size: contain !important; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='%23A1A1AA' stroke-width='1.8' stroke-linecap='round'%3E%3Cpath d='M4 4l8 8M12 4l-8 8'/%3E%3C/svg%3E") !important; }
div[class*="st-key-rm-attach"] button:hover { border-color: rgba(239, 68, 68, 0.4) !important; background: rgba(239, 68, 68, 0.1) !important; }
.poka-search-pill { display: inline-flex; align-items: center; gap: 7px; background: var(--accent-wash); border: 1px solid rgba(117, 102, 255, 0.3); color: var(--text-2); font-size: var(--fs-12); font-weight: 600; border-radius: var(--r-pill); padding: 7px 14px; }
.poka-search-mark { color: var(--accent-hover); display: inline-flex; }
.poka-search-mark svg { display: block; fill: currentColor; }
div[data-testid="stFileUploader"] { background: var(--bg-2); border: 1px solid var(--border); border-radius: var(--r-md); padding: var(--sp-8) var(--sp-12); }
div[data-testid="stFileUploader"] button { background: var(--bg-1); color: var(--text-1); border: 1px solid var(--border); border-radius: var(--r-sm); }
div[data-testid="stFileUploader"] button:hover { border-color: var(--border-strong); color: var(--text-1); }
div[data-testid="stCameraInput"] { border: 1px solid var(--border); border-radius: var(--r-md); padding: var(--sp-8); }
/* 11. ACCESSIBILITY */
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.st-key-composer [data-testid="stTextInput"] *:focus-visible { outline: none !important; }
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation-duration: 0.01ms !important; animation-iteration-count: 1 !important; transition-duration: 0.01ms !important; } .typing-indicator span:not(.typing-label) { animation: none; opacity: 0.6; } }
/* 12. HOME / EMPTY STATE */
.poka-home { text-align: center; max-width: 620px; margin: 0 auto; padding: var(--sp-32) var(--sp-24) 0; }
.poka-home-mark { width: 42px; height: 42px; border-radius: 13px; background: var(--accent-wash); border: 1px solid var(--border); display: inline-flex; align-items: center; justify-content: center; color: var(--accent-hover); box-shadow: var(--shadow-subtle); }
.poka-home-mark svg { display: block; fill: currentColor; }
.poka-eyebrow { font-size: var(--fs-12); font-weight: 650; letter-spacing: 0.1em; text-transform: uppercase; color: var(--text-3); margin: var(--sp-16) 0 0; }
.poka-home h1 { font-size: var(--fs-32); font-weight: 650; letter-spacing: -0.025em; color: var(--text-1); margin: var(--sp-8) 0 0; line-height: 1.2; }
.poka-home p { font-size: var(--fs-15); line-height: 1.65; color: var(--text-2); margin: var(--sp-8) auto 0; max-width: 540px; }
.st-key-home { max-width: 620px; margin: 0 auto; }
.st-key-home div[data-testid="stVerticalBlockBorderWrapper"] { background: transparent; border: 1px solid var(--border); border-radius: var(--r-md); padding: var(--sp-8) var(--sp-12); box-shadow: none; transition: background-color var(--dur) var(--ease), border-color var(--dur) var(--ease), transform var(--dur) var(--ease), box-shadow var(--dur) var(--ease); }
.st-key-home div[data-testid="stVerticalBlockBorderWrapper"]:hover { background: var(--bg-2); border-color: var(--border-strong); transform: translateY(-1px); box-shadow: var(--shadow-composer); }
.st-key-home div[class*="st-key-suggest-"] button { width: 100% !important; min-height: 32px !important; background: transparent !important; border: none !important; box-shadow: none !important; color: var(--text-1) !important; font-size: var(--fs-14) !important; font-weight: 650 !important; letter-spacing: -0.005em !important; text-align: left !important; padding: 2px 28px 2px 32px !important; white-space: normal !important; position: relative !important; }
.st-key-home div[class*="st-key-suggest-"] button::before { content: "" !important; position: absolute !important; left: 2px !important; top: 50% !important; translate: 0 -50% !important; width: 18px !important; height: 18px !important; background-repeat: no-repeat !important; background-position: center !important; background-size: contain !important; opacity: 0.85 !important; }
.st-key-home div[class*="st-key-suggest-"] button::after { content: "→" !important; position: absolute !important; right: 6px !important; top: 50% !important; translate: 0 -50% !important; font-size: var(--fs-14) !important; font-weight: 400 !important; color: var(--text-3) !important; transition: color var(--dur) var(--ease), transform var(--dur) var(--ease) !important; }
.st-key-home div[data-testid="stVerticalBlockBorderWrapper"]:hover div[class*="st-key-suggest-"] button::after { color: var(--accent-hover) !important; transform: translateX(2px) !important; }
.st-key-suggest-0 button::before { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='%23A1A1AA' stroke-width='1.4'%3E%3Crect x='2' y='2.5' width='12' height='8' rx='1.5'/%3E%3Cpath d='M6 13.5h4M8 10.5v3' stroke-linecap='round'/%3E%3C/svg%3E") !important; }
.st-key-suggest-1 button::before { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='%23A1A1AA' stroke-width='1.4'%3E%3Cpath d='M3 1.5h4.5L11 5v9.5H3z'/%3E%3Cpath d='M7.5 1.5V5H11'/%3E%3C/svg%3E") !important; }
.st-key-suggest-2 button::before { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='%23A1A1AA' stroke-width='1.4'%3E%3Ccircle cx='8' cy='8' r='6'/%3E%3Cpath d='M2 8h12M8 2c-3.5 3.5-3.5 8.5 0 12M8 2c3.5 3.5 3.5 8.5 0 12'/%3E%3C/svg%3E") !important; }
.st-key-suggest-3 button::before { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='%23A1A1AA'%3E%3Cpath d='M8 0l1.8 5.6L15 7l-4 3.6L12.2 16 8 12.8 3.8 16 5 10.6 1 7l5.2-1.4z'/%3E%3C/svg%3E") !important; }
.st-key-home div[data-testid="stCaptionContainer"] { text-align: left; color: var(--text-3); font-size: var(--fs-12); line-height: 1.5; }
/* 14. WORKSPACE — follow-up shortcuts + in-message file association */
.poka-follow-label { color: var(--text-3); font-size: 11px; text-transform: uppercase; letter-spacing: 0.09em; font-weight: 650; margin: var(--sp-8) auto 0; width: min(600px, 100%); }
.st-key-followups { width: min(600px, 100%); margin: 0 auto var(--sp-8); }
.st-key-followups [data-testid="stHorizontalBlock"] { gap: var(--sp-8) !important; }
.st-key-followups .stButton > button { width: 100%; background: transparent; border: 1px solid transparent; color: var(--text-3); font-size: var(--fs-12); font-weight: 600; border-radius: var(--r-pill); padding: 5px 10px; min-height: 30px; white-space: nowrap; }
.st-key-followups .stButton > button:hover { background: var(--bg-2); border-color: var(--border-strong); color: var(--text-1); transform: translateY(-1px); }
.st-key-followups .stButton > button:active { transform: scale(0.97); }
.poka-msg-file { margin: 0 0 var(--sp-8) auto; max-width: min(70%, 480px); }
.poka-msg-file .poka-file-row { background: var(--bg-2); border: 1px solid var(--border); border-radius: 10px; padding: 8px 12px; }
.poka-msg-file .poka-file-row:hover { background: var(--bg-2); }
/* 13. RESPONSIVE — 1440 / 1280 / 1024 / 900 / 768 / 700 / 480 / 390 */
@media (max-width: 1440px) { section[data-testid="stMain"] .block-container, div[data-testid="stMainBlockContainer"] { max-width: 680px; } }
@media (max-width: 1280px) { section[data-testid="stMain"] .block-container, div[data-testid="stMainBlockContainer"] { max-width: 660px; } .st-key-composer { width: min(600px, calc(100% - var(--sp-32))) !important; } }
@media (max-width: 1024px) { section[data-testid="stMain"] .block-container, div[data-testid="stMainBlockContainer"] { max-width: 640px; } .st-key-composer { width: min(600px, calc(100% - var(--sp-32))) !important; } div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]) div[data-testid="stChatMessageContent"] { max-width: 75%; } }
@media (max-width: 900px) { section[data-testid="stSidebar"] { width: 230px; } div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]) div[data-testid="stChatMessageContent"] { max-width: 80%; } .poka-home h1 { font-size: var(--fs-24); } }
@media (max-width: 768px) { section[data-testid="stMain"] .block-container, div[data-testid="stMainBlockContainer"] { padding-left: var(--sp-20); padding-right: var(--sp-20); } .st-key-composer { width: calc(100% - var(--sp-24)) !important; } .poka-chips { width: 100%; } div[data-testid="stImage"], div[data-testid="stImage"] img { max-width: 100%; } div[data-testid="stChatMessageContent"] table { font-size: 13px; } }
@media (max-width: 700px) { section[data-testid="stMain"] .block-container, div[data-testid="stMainBlockContainer"] { padding-left: var(--sp-16); padding-right: var(--sp-16); } .st-key-composer { width: calc(100% - var(--sp-24)) !important; bottom: var(--sp-12) !important; padding: 6px var(--sp-8) !important; border-radius: 20px !important; } .st-key-composer [data-testid="stHorizontalBlock"] { gap: var(--sp-4) !important; } .st-key-composer button { width: 34px !important; height: 34px !important; min-width: 34px !important; max-width: 34px !important; } .st-key-composer [data-testid="stTextInput"] input { font-size: var(--fs-14) !important; min-height: 36px !important; height: 36px !important; padding: var(--sp-8) 6px !important; } .st-key-attachment-menu { width: 248px !important; max-width: calc(100vw - var(--sp-32)) !important; } div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]) div[data-testid="stChatMessageContent"] { max-width: 85%; } .poka-msg-file { max-width: 85%; } div[class*="st-key-edit-"] div[data-testid="stBaseButton-secondary"] > button, div[class*="st-key-edit-"] .stButton > button { padding: 4px 10px; } div[data-testid="stChatMessageContent"] pre { padding: var(--sp-12); } .poka-error { padding: 10px var(--sp-12); } .poka-home { padding: var(--sp-20) var(--sp-16) 0; } }
@media (max-width: 480px) { .brand-title { font-size: var(--fs-20); } .poka-home h1 { font-size: 26px; } .st-key-composer { border-radius: var(--r-lg) !important; } .st-key-home [data-testid="stHorizontalBlock"] { flex-direction: column !important; gap: var(--sp-8) !important; } .st-key-home [data-testid="column"] { width: 100% !important; flex: 1 1 100% !important; min-width: 100% !important; } div[data-testid="stChatMessageContent"] { font-size: var(--fs-14); } .st-key-followups [data-testid="stHorizontalBlock"] { flex-wrap: wrap !important; } .st-key-followups [data-testid="column"] { flex: 1 1 calc(50% - var(--sp-4)) !important; min-width: calc(50% - var(--sp-4)) !important; } }
@media (max-width: 390px) { section[data-testid="stMain"] .block-container, div[data-testid="stMainBlockContainer"] { padding-left: var(--sp-12); padding-right: var(--sp-12); } .st-key-composer { width: calc(100% - var(--sp-16)) !important; bottom: var(--sp-8) !important; } div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]) div[data-testid="stChatMessageContent"] { max-width: 88%; padding: 10px 14px; } .poka-msg-file { max-width: 88%; } .st-key-attachment-menu { width: calc(100vw - var(--sp-32)) !important; } .poka-home { padding: var(--sp-16) var(--sp-12) 0; } .poka-home h1 { font-size: var(--fs-24); } .poka-model { max-width: 100%; } }
/* 15. RESEARCH — quiet selection state reusing the project-row language.
   The selected (disabled) brief row is unmistakable by surface + weight
   + accent edge, never color alone. No new visual system. */
div[class*="st-key-research-open-"] button:disabled {
    background: var(--accent-wash) !important;
    border: 1px solid rgba(117, 102, 255, 0.35) !important;
    box-shadow:inset 2px 0 0 var(--accent) !important;
    color: var(--text-1) !important;
    font-weight: 650 !important;
    opacity: 1 !important;
    cursor: default !important;
}
/* 17. NAVIGATION (7E) — secondary destinations sit behind compact
   disclosure rows driven by minimal sidebar_view state. Collapsed rows
   read as navigation; only the open destination shows its body. */
section[data-testid="stSidebar"] details { border: none !important; background: transparent !important; }
section[data-testid="stSidebar"] details > summary { font-size: var(--fs-14); font-weight: 600; color: var(--text-1); padding: var(--sp-8) var(--sp-8); border-radius: var(--r-sm); min-height: 36px; }
section[data-testid="stSidebar"] details > summary:hover { background: var(--bg-3); }
section[data-testid="stSidebar"] details > summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
/* 16. WORKFLOWS — selected option reuses the quiet selection language
   (surface + weight + accent edge, never color alone). Action rows keep
   a usable touch target; narrow layouts stack the two option columns. */
/* 18. NAV ROWS (7F) — selected destination reuses the quiet selection
   language (surface + weight + accent edge, never color alone). */
div[class*="st-key-nav-"] button:disabled {
    background: var(--accent-wash) !important;
    border: 1px solid rgba(117, 102, 255, 0.35) !important;
    box-shadow:inset 2px 0 0 var(--accent) !important;
    color: var(--text-1) !important;
    font-weight: 650 !important;
    opacity: 1 !important;
    cursor: default !important;
}
div[class*="st-key-workflow-select-"] button:disabled {
    background: var(--accent-wash) !important;
    border: 1px solid rgba(117, 102, 255, 0.35) !important;
    box-shadow:inset 2px 0 0 var(--accent-hover) !important;
    color: var(--text-1) !important;
    font-weight: 650 !important;
    opacity: 1 !important;
    cursor: default !important;
}
div[class*="st-key-workflow-"] button { min-height: 36px !important; }
@media (max-width: 480px) {
    div[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"]:has(div[class*="st-key-workflow-"]) { flex-wrap: wrap !important; }
}
"""


def apply_theme() -> None:
    """Inject the Poka theme into the page."""
    st.markdown("<style>" + THEME_CSS + "</style>", unsafe_allow_html=True)
