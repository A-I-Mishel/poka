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
/* 19. MODE TOGGLE (main area, above composer) — turns the two loose
   Fast/Deep buttons from app.py into one quiet segmented control that
   sits on the same 600px rail as the composer. Button faces reuse the
   existing st-key-mode- language (transparent idle, filled disabled =
   active); only the container is new. The third layout column in app.py
   (_mode_rest) carries no widgets, so it is hidden here to leave a
   clean 50/50 split. All selectors degrade gracefully: if the empty
   column ever gains content, the control simply shows blank space. */
section[data-testid="stMain"] div[data-testid="stHorizontalBlock"]:has(div[class*="st-key-mode-"]) { width: min(600px, 100%) !important; margin: var(--sp-4) auto 10px !important; gap: 0 !important; background: var(--bg-2) !important; border: 1px solid var(--border) !important; border-radius: var(--r-md) !important; padding: 3px !important; }
section[data-testid="stMain"] div[data-testid="stHorizontalBlock"]:has(div[class*="st-key-mode-"]) > div[data-testid="column"]:nth-child(3) { display: none !important; }
section[data-testid="stMain"] div[data-testid="stHorizontalBlock"]:has(div[class*="st-key-mode-"]) > div[data-testid="column"] { flex: 1 1 0 !important; min-width: 0 !important; padding: 0 !important; margin: 0 !important; }
section[data-testid="stMain"] div[class*="st-key-mode-"] button { min-height: 32px !important; border-radius: 9px !important; }
section[data-testid="stMain"] div[class*="st-key-mode-"] button:focus-visible { outline: 2px solid var(--accent) !important; outline-offset: 1px !important; }
/* 20. COMPOSER REFINEMENTS — frosted shell, calmer focus ring, tighter
   type. Specificity beats the base .st-key-composer rules above (same
   file, later position + section scope); every !important mirrors the
   load-bearing resets they override. */
.st-key-composer { backdrop-filter: blur(14px) !important; -webkit-backdrop-filter: blur(14px) !important; }
.st-key-composer:focus-within { border-color: rgba(117, 102, 255, 0.55) !important; box-shadow: var(--shadow-composer), 0 0 0 3px var(--accent-wash) !important; }
.st-key-composer [data-testid="stTextInput"] input { letter-spacing: -0.005em !important; }
/* 21. HOME REFINEMENTS — hero glow + eyebrow pill, cards on the bg-1
   surface with caption text aligned under the title (the title button
   reserves 32px for its icon), softer hover shadow, staggered rise-in.
   The global prefers-reduced-motion rule above already stills the new
   poka-rise animation for motion-sensitive users. */
@keyframes poka-rise { from { opacity: 0; translate: 0 8px; } to { opacity: 1; translate: 0 0; } }
.poka-home { max-width: 640px; animation: poka-rise 380ms var(--ease) both; }
.poka-home-mark { width: 46px; height: 46px; border-radius: 14px; box-shadow: var(--shadow-subtle), 0 0 28px rgba(117, 102, 255, 0.28); }
.poka-eyebrow { display: inline-block; background: var(--accent-wash); border: 1px solid rgba(117, 102, 255, 0.3); border-radius: var(--r-pill); padding: 5px var(--sp-12); }
.poka-home h1 { letter-spacing: -0.03em; text-wrap: balance; }
.st-key-home div[data-testid="stVerticalBlockBorderWrapper"] { background: var(--bg-1); border-radius: 14px; padding: var(--sp-12) 14px; min-height: 78px; display: flex; flex-direction: column; justify-content: center; animation: poka-rise 380ms var(--ease) both; }
.st-key-home div[data-testid="stVerticalBlockBorderWrapper"]:nth-child(2) { animation-delay: 60ms; }
.st-key-home div[data-testid="stVerticalBlockBorderWrapper"]:nth-child(3) { animation-delay: 120ms; }
.st-key-home div[data-testid="stVerticalBlockBorderWrapper"]:nth-child(4) { animation-delay: 180ms; }
.st-key-home div[data-testid="stVerticalBlockBorderWrapper"]:hover { border-color: rgba(117, 102, 255, 0.35); box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35); }
.st-key-home div[data-testid="stVerticalBlockBorderWrapper"]:hover div[class*="st-key-suggest-"] button::before { opacity: 1 !important; }
.st-key-home div[data-testid="stCaptionContainer"] { padding-left: 32px; margin-top: 1px; }
.st-key-home div[class*="st-key-suggest-"] button { line-height: 1.4 !important; }
.st-key-home div[class*="st-key-suggest-"] button:focus-visible { outline: 2px solid var(--accent) !important; outline-offset: 2px !important; border-radius: 6px !important; }
@media (max-width: 768px) { section[data-testid="stMain"] div[data-testid="stHorizontalBlock"]:has(div[class*="st-key-mode-"]) { width: calc(100% - var(--sp-24)) !important; } }
@media (max-width: 390px) { section[data-testid="stMain"] div[data-testid="stHorizontalBlock"]:has(div[class*="st-key-mode-"]) { width: calc(100% - var(--sp-16)) !important; } }
/* 22. SIDEBAR REFINEMENTS — hierarchy, search affordance, nav icons,
   touch targets. All selectors reuse the existing key language
   (st-key-chat-search, st-key-nav-*, stBaseButton-secondary) and degrade
   gracefully: icon/search rules only add decoration, never layout. */
/* 22a. Hierarchy — airier section rhythm, calmer dividers. */
section[data-testid="stSidebar"] .section-label { margin: 18px 0 6px !important; }
section[data-testid="stSidebar"] .poka-divider { margin: var(--sp-16) 0 !important; opacity: 1 !important; }
/* 22b. Search — magnifier inside the chat-search field only (project
   name/rename boxes keep their plain style). Background color comes from
   the base input rule above; only decoration is added here. */
section[data-testid="stSidebar"] div.st-key-chat-search input, section[data-testid="stSidebar"] div[class*="st-key-chat-search"] input { padding-left: 34px !important; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='%238E8E9A' stroke-width='1.6' stroke-linecap='round'%3E%3Ccircle cx='7' cy='7' r='4.5'/%3E%3Cpath d='M10.6 10.6L14 14'/%3E%3C/svg%3E") !important; background-repeat: no-repeat !important; background-position: 10px center !important; background-size: 15px 15px !important; }
/* 22c. Touch targets — every quiet sidebar row meets 36px. Scoped to
   secondary buttons only, so the primary New chat (stBaseButton-primary,
   own 40px rule) never collides. */
section[data-testid="stSidebar"] div[data-testid="stBaseButton-secondary"] > button { min-height: 36px !important; }
/* 22d. Nav icons — Workspace/More destinations carry marks aligned with
   row text, mirroring the project-row language. The More toggle keeps
   its text chevron and gets no icon. */
section[data-testid="stSidebar"] div[class*="st-key-nav-"] button { padding-left: 32px !important; position: relative !important; font-weight: 500 !important; }
section[data-testid="stSidebar"] div[class*="st-key-nav-"] button::before { content: "" !important; position: absolute !important; left: 10px !important; top: 50% !important; translate: 0 -50% !important; width: 15px !important; height: 15px !important; background-repeat: no-repeat !important; background-position: center !important; background-size: contain !important; opacity: 0.85 !important; }
section[data-testid="stSidebar"] .st-key-nav-research button::before { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='%23A1A1AA' stroke-width='1.4'%3E%3Ccircle cx='8' cy='8' r='6'/%3E%3Cpath d='M2 8h12M8 2c-3.5 3.5-3.5 8.5 0 12M8 2c3.5 3.5 3.5 8.5 0 12'/%3E%3C/svg%3E") !important; }
section[data-testid="stSidebar"] .st-key-nav-workflows button::before { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='%23A1A1AA'%3E%3Cpath d='M8 0l1.8 5.6L15 7l-4 3.6L12.2 16 8 12.8 3.8 16 5 10.6 1 7l5.2-1.4z'/%3E%3C/svg%3E") !important; }
section[data-testid="stSidebar"] .st-key-nav-memory button::before { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='%23A1A1AA' stroke-width='1.4' stroke-linejoin='round'%3E%3Cpath d='M4 2h8v12l-4-3.2L4 14z'/%3E%3C/svg%3E") !important; }
section[data-testid="stSidebar"] .st-key-nav-files button::before { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='%23A1A1AA' stroke-width='1.3'%3E%3Cpath d='M3 1h5l4 4v10H3z'/%3E%3Cpath d='M8 1v4h4'/%3E%3C/svg%3E") !important; }
section[data-testid="stSidebar"] .st-key-nav-artifacts button::before { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='%23A1A1AA' stroke-width='1.3'%3E%3Crect x='2' y='2.5' width='12' height='8' rx='1.5'/%3E%3Cpath d='M6 13.5h4M8 10.5v3' stroke-linecap='round'/%3E%3C/svg%3E") !important; }
section[data-testid="stSidebar"] .st-key-nav-sources button::before { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='%23A1A1AA' stroke-width='1.4' stroke-linecap='round'%3E%3Cpath d='M6.5 9.5l3-3'/%3E%3Cpath d='M7.5 4.5l1.5-1.5a2.5 2.5 0 0 1 3.5 3.5L11 8'/%3E%3Cpath d='M8.5 11.5L7 13a2.5 2.5 0 0 1-3.5-3.5L5 8'/%3E%3C/svg%3E") !important; }
section[data-testid="stSidebar"] .st-key-nav-stats button::before { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='%23A1A1AA' stroke-width='1.4' stroke-linecap='round'%3E%3Cpath d='M3 13V8M8 13V3M13 13v-5'/%3E%3C/svg%3E") !important; }
/* 22e. Account — model status reads as a full-width status row. */
section[data-testid="stSidebar"] .poka-model { width: 100%; box-sizing: border-box; border-radius: 10px; padding: var(--sp-8) 10px; margin-bottom: var(--sp-8); }
/* 23. CHAT MESSAGE REFINEMENTS — calmer turns, tappable follow-ups,
   grouped sources and artifacts. Same selectors as section 7, later
   position wins; class names and HTML are untouched. */
/* 23a. Readability + user bubble depth. text-wrap is progressive
   enhancement: older engines ignore it, layout never breaks. */
div[data-testid="stChatMessageContent"] { text-wrap: pretty; }
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]) div[data-testid="stChatMessageContent"] { padding: 10px 14px; box-shadow: var(--shadow-subtle); }
/* 23b. Follow-ups — bordered chips so they read as tappable at rest,
   not plain text. Hover language is unchanged (bg-2 + strong border). */
.st-key-followups .stButton > button { background: var(--bg-1); border: 1px solid var(--border); color: var(--text-2); }
.st-key-followups .stButton > button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
/* 23c. Typing — pill placeholder so "Thinking…" reads as a message in
   progress rather than floating dots. Dots and pulse are unchanged. */
.typing-indicator { display: flex; gap: 6px; padding: 10px var(--sp-16); align-items: center; background: var(--bg-1); border: 1px solid var(--border); border-radius: var(--r-pill); width: fit-content; max-width: 100%; box-shadow: var(--shadow-subtle); }
/* 23d. Sources — quiet accent edge groups the list under its heading. */
.poka-sources { border-left: 2px solid var(--border-strong); padding-left: var(--sp-12); }
/* 23e. In-message artifacts — card surface (shared with the workspace
   gallery, so both stay consistent). The border shorthand resets the
   old border-bottom-only look; expired dimming is preserved. */
.poka-art { background: var(--bg-1); border: 1px solid var(--border); border-radius: var(--r-md); padding: 10px var(--sp-12); margin: 0 0 var(--sp-8); box-shadow: var(--shadow-subtle); }
/* 24. MESSAGE ACTIONS — code-block copy pin + clustered meta buttons.
   The Listen button reuses .poka-copy, so it inherits reveal/hover for
   free; the time label takes auto margin so Copy + Listen cluster right
   instead of spreading across the row. */
div[data-testid="stChatMessageContent"] pre { position: relative; }
.poka-code-copy { position: absolute; top: var(--sp-8); right: var(--sp-8); display: inline-block; background: var(--bg-2); color: var(--text-3); border: 1px solid var(--border); border-radius: var(--r-pill); font-size: 11px; font-weight: 600; letter-spacing: 0.02em; padding: 4px 11px; margin: 0; cursor: pointer; opacity: 0; text-align: center; z-index: 3; transition: opacity var(--dur) var(--ease), background-color var(--dur) var(--ease), color var(--dur) var(--ease), border-color var(--dur) var(--ease); }
.poka-code-copy:hover { color: var(--text-1); border-color: var(--border-strong); }
.poka-code-copy:active { transform: scale(0.95); }
.poka-code-copy:focus-visible { opacity: 1; outline: 2px solid var(--accent); outline-offset: 2px; }
div[data-testid="stChatMessageContent"] pre:hover .poka-code-copy { opacity: 1; }
@media (hover: none) { .poka-code-copy { opacity: 1; } }
.poka-meta .poka-time { margin-right: auto; }
.poka-meta .poka-copy + .poka-copy { margin-left: 2px; }
/* Regenerate (latest assistant reply) — quiet ghost pill mirroring the
   user-message Edit action. Scoped to regen-msg- so the artifact
   Regenerate buttons (regen-chat-, regen-side-) keep their own style. */
div[class*="st-key-regen-msg-"] { display: flex; justify-content: flex-end; }
div[class*="st-key-regen-msg-"] div[data-testid="stBaseButton-secondary"] > button, div[class*="st-key-regen-msg-"] .stButton > button { width: auto; background: transparent; border: 1px solid transparent; color: var(--text-3); font-size: var(--fs-12); font-weight: 600; border-radius: var(--r-pill); padding: 4px 14px; text-align: center; min-height: 30px; white-space: nowrap; }
div[class*="st-key-regen-msg-"] div[data-testid="stBaseButton-secondary"] > button:hover, div[class*="st-key-regen-msg-"] .stButton > button:hover { color: var(--text-1); border-color: var(--border); background: var(--bg-2); transform: none; }
/* 25. TRACK 1 — NEXT-LEVEL POLISH (design only, zero features).
   Purely additive: every rule wins by later position over its earlier
   section; no selector, key, class, or behavior contract is removed. */
/* 25a. Contrast — tertiary text one step brighter for small-text
   legibility on the near-black surfaces. Single token override; every
   usage (captions, markers, placeholders, meta) follows automatically. */
:root { --text-3: #8e8e9a; }
/* 25b. Selection tint. */
::selection { background: rgba(117, 102, 255, 0.35); color: var(--text-1); }
/* 25c. Hero headline gradient (progressive enhancement — engines
   without background-clip keep the solid token color from section 12). */
@supports ((-webkit-background-clip: text) or (background-clip: text)) {
    .poka-home h1 { background: linear-gradient(180deg, #ffffff 25%, #b6b6c8 100%); -webkit-background-clip: text; background-clip: text; color: transparent; -webkit-text-fill-color: transparent; }
}
/* 25d. Workspace rail — wider measure for tables, galleries, and briefs
   while chat keeps its 680px measure. Detected purely by the Back to
   chat control every workspace view renders; when absent (normal chat)
   nothing changes. max-width is an upper bound, so narrow screens with
   their own padding rules are unaffected. */
section[data-testid="stMain"]:has(div[class*="st-key-back-to-chat"]) .block-container, section[data-testid="stMain"]:has(div[class*="st-key-back-to-chat"]) div[data-testid="stMainBlockContainer"] { max-width: 920px; }
/* 25e. Assistant card — quiet surface grouping each answer. Header,
   typing pill, meta row, and message actions keep their own rules; only
   the content block gains the card. Nested pre/blockquote keep
   definition through their own borders. */
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarAssistant"]) div[data-testid="stChatMessageContent"] { background: var(--bg-1); border: 1px solid var(--border); border-radius: var(--r-lg); padding: var(--sp-16); box-shadow: var(--shadow-subtle); }
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarAssistant"]):hover div[data-testid="stChatMessageContent"] { border-color: var(--border-strong); }
@media (max-width: 700px) { div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarAssistant"]) div[data-testid="stChatMessageContent"] { padding: var(--sp-12); } }
/* 25f. Citation chips — source rows read as tappable cards; the index
   becomes an accent badge. Applies everywhere the shared source markup
   renders (answers, Sources view, brief viewer) for one language. */
.poka-source { background: var(--bg-2); border: 1px solid var(--border); border-radius: 10px; padding: 7px var(--sp-12); margin: 0 0 6px; transition: border-color var(--dur) var(--ease), background-color var(--dur) var(--ease); }
.poka-source:hover { border-color: var(--border-strong); }
.poka-source-n { background: var(--accent-wash); color: var(--accent-hover); border-radius: 6px; padding: 1px 7px; font-weight: 700; }
/* 25g. Workspace empty states — dashed card treatment, main area only
   (sidebar .poka-empty rows keep their quiet inline style). */
section[data-testid="stMain"] .poka-empty { text-align: center; border: 1px dashed var(--border-strong); border-radius: var(--r-md); padding: var(--sp-20) var(--sp-16); margin: var(--sp-12) 0; font-size: var(--fs-14); line-height: 1.6; }
/* 25h. Table headers — tinted row so wide data tables scan in the card. */
div[data-testid="stChatMessageContent"] thead th { background: var(--bg-2); }
/* 26. NEXT-LEVEL POLISH — atmosphere, type, depth (design only, zero
   features). Purely additive: later position wins over sections 1-25;
   no selector, key, class, or behavior contract is removed. */
/* 26a. Extended tokens (additive only — base tokens above untouched). */
:root {
    --font-display: 'Space Grotesk', 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif;
    --font-mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    --accent-soft: #9d8cff; --accent-muted: rgba(117, 102, 255, 0.28);
    --glow-accent: 0 0 28px rgba(117, 102, 255, 0.22);
    --inner-hi: inset 0 1px 0 rgba(255, 255, 255, 0.05);
    --shadow-lift: 0 10px 28px rgba(0, 0, 0, 0.42);
}
/* 26b. Atmosphere — aurora wash over the near-black base. Single
   background layer on .stApp only; Main/Sidebar keep their surfaces
   so readability never depends on the glow. */
.stApp {
    background:
        radial-gradient(1100px 520px at 50% -8%, rgba(117, 102, 255, 0.09), transparent 62%),
        radial-gradient(800px 420px at 88% 12%, rgba(117, 102, 255, 0.05), transparent 60%),
        var(--bg-0) !important;
}
/* 26c. Display type — hero + brand word only. Body/UI stay Inter. */
.poka-home h1, .brand-title, .poka-word { font-family: var(--font-display) !important; }
.poka-home h1 { font-weight: 700 !important; letter-spacing: -0.035em !important; }
.brand-title { font-weight: 700 !important; letter-spacing: -0.025em !important; }
.poka-word { font-weight: 700 !important; }
/* 26d. Mono — code only (chat markdown + sidebar-proof). */
div[data-testid="stChatMessageContent"] code, div[data-testid="stChatMessageContent"] pre code { font-family: var(--font-mono) !important; font-size: 12.8px !important; letter-spacing: -0.002em !important; }
/* 26e. Brand marks — gradient identity, white glyph. */
.poka-mark, .poka-home-mark {
    background: linear-gradient(135deg, #7566ff 0%, #9d8cff 100%) !important;
    border-color: rgba(157, 140, 255, 0.55) !important;
    color: #fff !important;
    box-shadow: var(--shadow-subtle), var(--glow-accent) !important;
}
.poka-assistant-mark {
    background: linear-gradient(135deg, rgba(117,102,255,0.32), rgba(117,102,255,0.12)) !important;
    border-color: rgba(117, 102, 255, 0.4) !important;
    color: var(--accent-soft) !important;
}
/* 26f. Turn-taking — user bubble goes accent-tinted, assistant stays
   neutral. Same shape/padding/selectors, only surface changes. */
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]) div[data-testid="stChatMessageContent"] {
    background: linear-gradient(180deg, rgba(117, 102, 255, 0.14), rgba(117, 102, 255, 0.07)) !important;
    border-color: rgba(117, 102, 255, 0.3) !important;
    box-shadow: var(--shadow-subtle), var(--inner-hi) !important;
}
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]):hover div[data-testid="stChatMessageContent"] { border-color: rgba(117, 102, 255, 0.5) !important; }
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarAssistant"]) div[data-testid="stChatMessageContent"] { box-shadow: var(--shadow-subtle), var(--inner-hi) !important; }
/* 26g. Composer — deeper frost + accent glow on focus. */
.st-key-composer {
    backdrop-filter: blur(20px) saturate(1.4) !important; -webkit-backdrop-filter: blur(20px) saturate(1.4) !important;
    background: rgba(14, 14, 19, 0.86) !important; background-color: rgba(14, 14, 19, 0.86) !important;
    box-shadow: var(--shadow-composer), var(--inner-hi) !important;
}
.st-key-composer:focus-within {
    border-color: rgba(117, 102, 255, 0.6) !important;
    box-shadow: var(--shadow-composer), 0 0 0 3px var(--accent-wash), var(--glow-accent) !important;
}
/* 26h. Calm buttons — cards may lift, buttons only fade (no layout
   jitter across Streamlit reruns). */
section[data-testid="stSidebar"] div[data-testid="stBaseButton-primary"] > button:hover { transform: none !important; box-shadow: 0 0 0 3px var(--accent-wash), var(--shadow-subtle) !important; }
.st-key-composer [data-testid="column"]:last-child button:hover { transform: none !important; box-shadow: 0 0 0 3px var(--accent-wash), var(--shadow-subtle) !important; }
.st-key-followups .stButton > button:hover { transform: none !important; }
.st-key-home div[data-testid="stVerticalBlockBorderWrapper"] { box-shadow: var(--shadow-subtle), var(--inner-hi) !important; min-height: 84px !important; }
.st-key-home div[data-testid="stVerticalBlockBorderWrapper"]:hover { transform: translateY(-2px) !important; border-color: rgba(117, 102, 255, 0.4) !important; box-shadow: var(--shadow-lift), var(--glow-accent) !important; }
/* 26i. Entrance — soft rise for new turns (reduced-motion stills it
   via the global rule in section 11). */
@keyframes poka-in { from { opacity: 0; translate: 0 6px; } to { opacity: 1; translate: 0 0; } }
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]) div[data-testid="stChatMessageContent"],
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarAssistant"]) div[data-testid="stChatMessageContent"] { animation: poka-in 220ms var(--ease) both !important; }
/* 26j. Code depth — header breathing room for the pinned copy btn. */
div[data-testid="stChatMessageContent"] pre { box-shadow: var(--shadow-subtle), var(--inner-hi) !important; }
div[data-testid="stChatMessageContent"] pre code { padding-right: 64px !important; }
/* 27. CHATGPT-STYLE (design only, zero features). ChatGPT reads calm
    because it is neutral, flat, and quiet: solid grays, no aurora, no
    gradients, plain assistant turns, gray user bubbles, white send dot.
    Purely additive: later position wins over sections 1-26; no selector,
    key, class, or behavior contract is removed. Test-token strings
    (264px, media queries, st-key-*, poka-sources, ellipsis) all live in
    the earlier sections above and are intentionally left untouched. */
:root {
    --bg-0: #212121; --bg-1: #171717; --bg-2: #2f2f2f; --bg-3: #3d3d3d;
    --border: #3d3d3d; --border-strong: #565656;
    --text-1: #ececec; --text-2: #b4b4b4;
    --shadow-subtle: 0 1px 2px rgba(0, 0, 0, 0.3);
    --shadow-composer: 0 2px 12px rgba(0, 0, 0, 0.25);
    --shadow-menu: 0 8px 28px rgba(0, 0, 0, 0.5);
    --shadow-lift: 0 4px 16px rgba(0, 0, 0, 0.3);
    --glow-accent: 0 0 0 rgba(0, 0, 0, 0);
    --inner-hi: inset 0 0 0 rgba(0, 0, 0, 0);
}
/* 27a. Flat atmosphere — solid main, solid sidebar. */
.stApp { background: var(--bg-0) !important; }
section[data-testid="stSidebar"] { background: var(--bg-1) !important; border-right: 1px solid #2e2e2e !important; }
header[data-testid="stHeader"] { background: rgba(33, 33, 33, 0.0); }
/* 27b. Measure — ChatGPT 768px column for reading + workspace. */
section[data-testid="stMain"] .block-container, div[data-testid="stMainBlockContainer"] { max-width: 768px !important; }
section[data-testid="stMain"]:has(div[class*="st-key-back-to-chat"]) .block-container, section[data-testid="stMain"]:has(div[class*="st-key-back-to-chat"]) div[data-testid="stMainBlockContainer"] { max-width: 768px !important; }
/* 27c. Type — system voice, no display face. */
.poka-home h1, .brand-title, .poka-word { font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif !important; }
.poka-home h1 { font-weight: 400 !important; letter-spacing: -0.01em !important; font-size: var(--fs-32) !important; background: none !important; color: var(--text-1) !important; -webkit-text-fill-color: var(--text-1) !important; }
.brand-title { font-weight: 600 !important; letter-spacing: -0.01em !important; }
.poka-word { font-weight: 600 !important; }
/* 27d. Identity marks — monochrome, no gradient glow. */
.poka-mark, .poka-home-mark { background: var(--bg-2) !important; border-color: var(--border) !important; color: var(--text-1) !important; box-shadow: none !important; }
.poka-assistant-mark { background: var(--bg-2) !important; border-color: var(--border) !important; color: var(--text-2) !important; }
.poka-home-mark { box-shadow: none !important; }
/* 27e. Hero — plain prompt, no eyebrow pill. */
.poka-eyebrow { display: block !important; background: none !important; border: none !important; padding: 0 !important; color: var(--text-2) !important; font-weight: 500 !important; letter-spacing: 0.02em !important; text-transform: none !important; font-size: var(--fs-14) !important; }
.poka-home p { color: var(--text-2) !important; }
/* 27f. Turns — plain assistant text, gray user bubble (ChatGPT). */
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarAssistant"]) div[data-testid="stChatMessageContent"] { background: transparent !important; border: none !important; border-radius: 0 !important; padding: 6px 2px var(--sp-8) !important; box-shadow: none !important; }
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarAssistant"]):hover div[data-testid="stChatMessageContent"] { border-color: transparent !important; }
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]) div[data-testid="stChatMessageContent"] { background: var(--bg-2) !important; border: 1px solid transparent !important; border-radius: 20px !important; padding: 10px var(--sp-16) !important; box-shadow: none !important; }
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]):hover div[data-testid="stChatMessageContent"] { border-color: transparent !important; background: var(--bg-3) !important; }
/* 27g. Composer — flat gray pill, white send dot with dark arrow. */
.st-key-composer { backdrop-filter: none !important; -webkit-backdrop-filter: none !important; background: var(--bg-2) !important; background-color: var(--bg-2) !important; border: 1px solid transparent !important; border-radius: 28px !important; box-shadow: none !important; }
.st-key-composer:focus-within { border-color: var(--border-strong) !important; box-shadow: none !important; }
.st-key-composer [data-testid="column"]:last-child button { background: #ffffff !important; background-color: #ffffff !important; border: 1px solid #ffffff !important; box-shadow: none !important; }
.st-key-composer [data-testid="column"]:last-child button::after { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='%23212121' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M8 13.5v-11M3.5 7.5L8 3l4.5 4.5'/%3E%3C/svg%3E") !important; }
.st-key-composer [data-testid="column"]:last-child button:hover { background: #ececec !important; background-color: #ececec !important; border-color: #ececec !important; box-shadow: none !important; transform: none !important; }
.st-key-composer [data-testid="column"]:last-child button:active { background: #d9d9d9 !important; background-color: #d9d9d9 !important; border-color: #d9d9d9 !important; transform: scale(0.94) !important; }
.st-key-composer [data-testid="column"]:first-child button:hover { background: var(--bg-3) !important; background-color: var(--bg-3) !important; }
/* 27h. Home cards — quiet outline rows, no lift or glow. */
.st-key-home div[data-testid="stVerticalBlockBorderWrapper"] { background: transparent !important; border-radius: var(--r-lg) !important; min-height: 0 !important; box-shadow: none !important; }
.st-key-home div[data-testid="stVerticalBlockBorderWrapper"]:hover { background: var(--bg-2) !important; border-color: var(--border-strong) !important; transform: none !important; box-shadow: none !important; }
/* 27i. Sidebar primary — outline like ChatGPT New chat; accent stays
    only on selected rows + focus rings from earlier sections. */
section[data-testid="stSidebar"] div[data-testid="stBaseButton-primary"] > button { background: transparent !important; border: 1px solid var(--border-strong) !important; color: var(--text-1) !important; box-shadow: none !important; }
section[data-testid="stSidebar"] div[data-testid="stBaseButton-primary"] > button:hover { background: var(--bg-2) !important; border-color: var(--border-strong) !important; transform: none !important; box-shadow: none !important; }
section[data-testid="stSidebar"] div[data-testid="stBaseButton-primary"] > button:active { background: var(--bg-3) !important; transform: none !important; box-shadow: none !important; }
/* 27j. Mode segmented — neutral active, no accent fill. */
section[data-testid="stMain"] div[data-testid="stHorizontalBlock"]:has(div[class*="st-key-mode-"]) { background: transparent !important; border: none !important; padding: 0 !important; gap: var(--sp-8) !important; }
section[data-testid="stMain"] div[class*="st-key-mode-"] button { border: 1px solid var(--border) !important; border-radius: var(--r-pill) !important; color: var(--text-2) !important; }
section[data-testid="stMain"] div[class*="st-key-mode-"] button:hover:not(:disabled) { background: var(--bg-2) !important; color: var(--text-1) !important; }
section[data-testid="stMain"] div[class*="st-key-mode-"] button:disabled { background: var(--bg-2) !important; border-color: var(--border-strong) !important; color: var(--text-1) !important; box-shadow: none !important; }
/* 27k. Code, sources, artifacts, follow-ups — flat neutrals. */
div[data-testid="stChatMessageContent"] pre { background: #1a1a1a !important; box-shadow: none !important; }
.typing-indicator { background: var(--bg-2) !important; border-color: transparent !important; box-shadow: none !important; }
.poka-sources { border-left: 1px solid var(--border-strong) !important; }
.poka-source { background: transparent !important; }
.poka-source:hover { background: var(--bg-2) !important; border-color: var(--border-strong) !important; }
.poka-source-n { background: var(--bg-3) !important; color: var(--text-1) !important; }
.poka-art { background: transparent !important; box-shadow: none !important; }
.poka-art:hover { background: var(--bg-2) !important; }
.st-key-followups .stButton > button { background: transparent !important; }
.st-key-followups .stButton > button:hover { background: var(--bg-2) !important; transform: none !important; }
section[data-testid="stMain"] .poka-empty { border-style: solid !important; }
::selection { background: rgba(255, 255, 255, 0.22) !important; }
/* 27l. Hardened key-based overrides (same ChatGPT look, higher
    specificity so they win even if column/testid selectors shift
    across Streamlit builds). No new look, just robust anchors. */
.st-key-new-chat button { background: transparent !important; background-color: transparent !important; border: 1px solid var(--border-strong) !important; color: var(--text-1) !important; box-shadow: none !important; }
.st-key-new-chat button:hover { background: var(--bg-2) !important; background-color: var(--bg-2) !important; }
.st-key-composer_send button { background: #ffffff !important; background-color: #ffffff !important; border: 1px solid #ffffff !important; color: #212121 !important; }
.st-key-composer_send button:hover { background: #ececec !important; background-color: #ececec !important; border-color: #ececec !important; }
section[data-testid="stSidebar"] .stButton > button:not(:disabled) { border-color: transparent !important; }
section[data-testid="stSidebar"] .st-key-new-chat button:not(:disabled) { border-color: var(--border-strong) !important; }
section[data-testid="stMain"] div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarAssistant"]) div[data-testid="stChatMessageContent"] { background: transparent !important; border: none !important; box-shadow: none !important; }
section[data-testid="stMain"] div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]) div[data-testid="stChatMessageContent"] { background: var(--bg-2) !important; border: 1px solid transparent !important; box-shadow: none !important; width: fit-content !important; }
section[data-testid="stMain"] .st-key-composer { background: var(--bg-2) !important; background-color: var(--bg-2) !important; border: 1px solid transparent !important; box-shadow: none !important; }
/* 27m. Follow-ups retired — belt-and-braces hide so stale renders stay
    invisible too. Python no longer emits this block at all. */
.st-key-followups, .poka-follow-label { display: none !important; }
/* 27n. In-composer mode pill — text button, not an icon dot. The base
    composer rule hides button text (font-size: 0) for the round icon
    cells, so this re-enables type and kills the ::after glyph. Key is
    composer-mode on purpose: the legacy st-key-mode- row selectors must
    never match inside the bar. Matched by key class AND by column
    position, so it survives key-class shifts across Streamlit builds. */
.st-key-composer [data-testid="column"]:nth-child(2) { min-width: 64px !important; }
.st-key-composer [data-testid="column"]:nth-child(2) button,
.st-key-composer .st-key-composer-mode button { width: auto !important; min-width: 0 !important; max-width: none !important; height: 30px !important; min-height: 30px !important; padding: 0 var(--sp-12) !important; border-radius: var(--r-pill) !important; font-size: var(--fs-12) !important; font-weight: 600 !important; letter-spacing: 0.02em !important; background: transparent !important; background-color: transparent !important; border: 1px solid var(--border-strong) !important; color: var(--text-2) !important; white-space: nowrap !important; }
.st-key-composer [data-testid="column"]:nth-child(2) button::after,
.st-key-composer .st-key-composer-mode button::after { content: none !important; display: none !important; width: 0 !important; height: 0 !important; }
.st-key-composer [data-testid="column"]:nth-child(2) button:hover,
.st-key-composer .st-key-composer-mode button:hover { background: var(--bg-3) !important; background-color: var(--bg-3) !important; color: var(--text-1) !important; }
@media (max-width: 700px) { .st-key-composer [data-testid="column"]:nth-child(2) button, .st-key-composer .st-key-composer-mode button { padding: 0 10px !important; } }
/* 28. SIDEBAR RAIL — ChatGPT-style navigation (design only, zero
    features). Every action is a full-width borderless row; boxed pills
    are gone. Purely additive: later position wins; keys, testids, and
    the disabled (selected) states keep their accent edge. Selectors
    cover every Streamlit button generation (stButton testid, stButton
    class, stBaseButton-*) so rows never fall back to boxed defaults. */
/* 28a. Rows — fill the cell, left aligned, calm type. */
section[data-testid="stSidebar"] div[data-testid="stButton"] > button:not(:disabled),
section[data-testid="stSidebar"] div[data-testid="stBaseButton-secondary"] > button:not(:disabled),
section[data-testid="stSidebar"] .stButton > button:not(:disabled) { width: 100% !important; text-align: left !important; justify-content: flex-start !important; background: transparent !important; background-color: transparent !important; border: 1px solid transparent !important; border-radius: 10px !important; box-shadow: none !important; min-height: 38px !important; padding: 8px var(--sp-12) !important; font-size: var(--fs-14) !important; font-weight: 500 !important; color: var(--text-1) !important; white-space: nowrap !important; overflow: hidden !important; text-overflow: ellipsis !important; }
section[data-testid="stSidebar"] div[data-testid="stButton"] > button:not(:disabled):hover,
section[data-testid="stSidebar"] div[data-testid="stBaseButton-secondary"] > button:not(:disabled):hover,
section[data-testid="stSidebar"] .stButton > button:not(:disabled):hover { background: var(--bg-2) !important; background-color: var(--bg-2) !important; border-color: var(--border) !important; color: var(--text-1) !important; transform: none !important; }
/* 28b. New chat — full-width quiet anchor, never boxed. */
section[data-testid="stSidebar"] div[data-testid="stButton"] > button[kind="primary"],
section[data-testid="stSidebar"] div[data-testid="stBaseButton-primary"] > button,
.st-key-new-chat button { width: 100% !important; text-align: left !important; justify-content: flex-start !important; background: transparent !important; background-color: transparent !important; border: 1px solid var(--border-strong) !important; border-radius: 10px !important; box-shadow: none !important; min-height: 40px !important; font-weight: 600 !important; color: var(--text-1) !important; }
section[data-testid="stSidebar"] div[data-testid="stButton"] > button[kind="primary"]:hover,
section[data-testid="stSidebar"] div[data-testid="stBaseButton-primary"] > button:hover,
.st-key-new-chat button:hover { background: var(--bg-2) !important; background-color: var(--bg-2) !important; transform: none !important; }
/* 28c. Rhythm — labels clear the rows above; search keeps its own lane
    so it can never overlap the PROJECTS header. */
section[data-testid="stSidebar"] .section-label { display: block !important; margin: 20px 0 6px !important; padding: 0 4px !important; }
section[data-testid="stSidebar"] div[data-testid="stTextInput"] { margin-bottom: 6px !important; }
/* 28d. Downloads + model status span the rail like everything else. */
section[data-testid="stSidebar"] div[data-testid="stDownloadButton"] > button { width: 100% !important; justify-content: flex-start !important; text-align: left !important; }
/* 29. PREMIUM DARK + ACCENT (design only, zero features). Richer depth
    over the flat ChatGPT grays: deep near-black base, layered surfaces,
    violet accent used sparingly (send, active rows, focus, hero glow).
    Purely additive: later position wins over sections 1-28; no selector,
    key, class, or behavior contract is removed. All test-token strings
    (264px, media queries, st-key-*, poka-sources, ellipsis, transparent,
    var(--bg-2)) live in earlier sections and are left untouched. */
:root {
    --bg-0: #09090e; --bg-1: #101016; --bg-2: #191922; --bg-3: #23232f;
    --border: #23232f; --border-strong: #3b3b4d;
    --text-1: #f4f4f7; --text-2: #b9b9c7; --text-3: #9a9aa8;
    --accent: #7c6cff; --accent-hover: #8e7dff; --accent-pressed: #6655e8;
    --accent-wash: rgba(124, 108, 255, 0.13);
    --accent-line: rgba(124, 108, 255, 0.38);
    --shadow-subtle: 0 1px 2px rgba(0, 0, 0, 0.4);
    --shadow-composer: 0 16px 44px rgba(0, 0, 0, 0.55);
    --shadow-menu: 0 20px 48px rgba(0, 0, 0, 0.55);
    --shadow-lift: 0 12px 32px rgba(0, 0, 0, 0.45);
    --glow-accent: 0 0 32px rgba(124, 108, 255, 0.28);
    --inner-hi: inset 0 1px 0 rgba(255, 255, 255, 0.06);
}
/* 29a. Atmosphere — aurora wash, readability stays on solid surfaces. */
.stApp {
    background:
        radial-gradient(1100px 480px at 50% -8%, rgba(124, 108, 255, 0.11), transparent 62%),
        radial-gradient(760px 400px at 88% 10%, rgba(80, 140, 255, 0.06), transparent 60%),
        radial-gradient(700px 500px at 8% 100%, rgba(124, 108, 255, 0.05), transparent 60%),
        var(--bg-0) !important;
}
section[data-testid="stSidebar"] { background: var(--bg-1) !important; border-right: 1px solid var(--border) !important; }
::selection { background: rgba(124, 108, 255, 0.38) !important; color: #fff !important; }
/* 29b. Type — display face for hero + brand only, mono for code. */
.poka-home h1, .brand-title, .poka-word { font-family: 'Space Grotesk', 'Inter', system-ui, sans-serif !important; }
.poka-home h1 { font-weight: 700 !important; letter-spacing: -0.035em !important; font-size: var(--fs-32) !important; }
@supports ((-webkit-background-clip: text) or (background-clip: text)) {
    .poka-home h1 { background: linear-gradient(180deg, #ffffff 20%, #c4b8ff 100%) !important; -webkit-background-clip: text !important; background-clip: text !important; color: transparent !important; -webkit-text-fill-color: transparent !important; }
}
.brand-title { font-weight: 700 !important; }
div[data-testid="stChatMessageContent"] code, div[data-testid="stChatMessageContent"] pre code { font-family: 'JetBrains Mono', ui-monospace, monospace !important; font-size: 12.8px !important; }
/* 29c. Identity — gradient brand marks with glow. */
.poka-mark, .poka-home-mark { background: linear-gradient(135deg, #7c6cff 0%, #a394ff 100%) !important; border-color: rgba(163, 148, 255, 0.6) !important; color: #fff !important; box-shadow: var(--shadow-subtle), var(--glow-accent) !important; }
.poka-home-mark { width: 46px !important; height: 46px !important; border-radius: 14px !important; }
.poka-assistant-mark { background: linear-gradient(135deg, rgba(124,108,255,0.32), rgba(124,108,255,0.1)) !important; border-color: var(--accent-line) !important; color: #b3a6ff !important; }
.poka-eyebrow { display: inline-block !important; background: var(--accent-wash) !important; border: 1px solid var(--accent-line) !important; border-radius: var(--r-pill) !important; padding: 5px var(--sp-12) !important; color: #c9c0ff !important; font-size: var(--fs-12) !important; font-weight: 650 !important; letter-spacing: 0.08em !important; text-transform: uppercase !important; }
/* 29d. Sidebar rows — calm hover, unmistakable active (surface + weight + accent edge). */
section[data-testid="stSidebar"] div[data-testid="stButton"] > button:not(:disabled):hover,
section[data-testid="stSidebar"] div[data-testid="stBaseButton-secondary"] > button:not(:disabled):hover,
section[data-testid="stSidebar"] .stButton > button:not(:disabled):hover { background: var(--bg-2) !important; border-color: var(--border) !important; }
section[data-testid="stSidebar"] div[data-testid="stBaseButton-primary"] > button,
section[data-testid="stSidebar"] div[data-testid="stButton"] > button[kind="primary"],
.st-key-new-chat button { background: linear-gradient(135deg, #7c6cff 0%, #8e7dff 100%) !important; background-color: #7c6cff !important; border: 1px solid rgba(163,148,255,0.5) !important; color: #fff !important; font-weight: 650 !important; box-shadow: 0 4px 18px rgba(124,108,255,0.32), var(--inner-hi) !important; }
section[data-testid="stSidebar"] div[data-testid="stBaseButton-primary"] > button:hover,
section[data-testid="stSidebar"] div[data-testid="stButton"] > button[kind="primary"]:hover,
.st-key-new-chat button:hover { background: linear-gradient(135deg, #8e7dff 0%, #a394ff 100%) !important; background-color: var(--accent-hover) !important; box-shadow: 0 6px 24px rgba(124,108,255,0.42), var(--inner-hi) !important; transform: none !important; }
/* 29e. Turns — accent-tinted user bubble, assistant card. */
section[data-testid="stMain"] div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]) div[data-testid="stChatMessageContent"] { background: linear-gradient(180deg, rgba(124,108,255,0.16), rgba(124,108,255,0.08)) !important; border: 1px solid rgba(124,108,255,0.32) !important; border-radius: 18px !important; padding: 10px var(--sp-16) !important; box-shadow: var(--shadow-subtle), var(--inner-hi) !important; width: fit-content !important; }
section[data-testid="stMain"] div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]):hover div[data-testid="stChatMessageContent"] { border-color: rgba(124,108,255,0.52) !important; background: linear-gradient(180deg, rgba(124,108,255,0.19), rgba(124,108,255,0.1)) !important; }
section[data-testid="stMain"] div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarAssistant"]) div[data-testid="stChatMessageContent"] { background: var(--bg-1) !important; border: 1px solid var(--border) !important; border-radius: var(--r-lg) !important; padding: var(--sp-16) !important; box-shadow: var(--shadow-subtle), var(--inner-hi) !important; }
section[data-testid="stMain"] div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarAssistant"]):hover div[data-testid="stChatMessageContent"] { border-color: var(--border-strong) !important; }
/* 29f. Composer — frosted floating bar with accent focus glow. */
section[data-testid="stMain"] .st-key-composer { background: rgba(20, 20, 29, 0.88) !important; background-color: rgba(20, 20, 29, 0.88) !important; backdrop-filter: blur(20px) saturate(1.4) !important; -webkit-backdrop-filter: blur(20px) saturate(1.4) !important; border: 1px solid var(--border) !important; border-radius: 26px !important; box-shadow: var(--shadow-composer), var(--inner-hi) !important; }
section[data-testid="stMain"] .st-key-composer:focus-within { border-color: rgba(124,108,255,0.6) !important; box-shadow: var(--shadow-composer), 0 0 0 3px var(--accent-wash), var(--glow-accent) !important; }
.st-key-composer [data-testid="column"]:last-child button, .st-key-composer_send button { background: linear-gradient(135deg, #7c6cff 0%, #9d8cff 100%) !important; background-color: #7c6cff !important; border: 1px solid rgba(163,148,255,0.55) !important; box-shadow: 0 4px 16px rgba(124,108,255,0.4) !important; }
.st-key-composer [data-testid="column"]:last-child button::after, .st-key-composer_send button::after { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='white' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M8 13.5v-11M3.5 7.5L8 3l4.5 4.5'/%3E%3C/svg%3E") !important; }
.st-key-composer [data-testid="column"]:last-child button:hover, .st-key-composer_send button:hover { background: linear-gradient(135deg, #8e7dff 0%, #b0a1ff 100%) !important; background-color: var(--accent-hover) !important; box-shadow: 0 6px 22px rgba(124,108,255,0.5) !important; transform: none !important; }
/* 29g. Home cards — surface + lift on hover. */
.st-key-home div[data-testid="stVerticalBlockBorderWrapper"] { background: var(--bg-1) !important; border-radius: 14px !important; box-shadow: var(--shadow-subtle), var(--inner-hi) !important; }
.st-key-home div[data-testid="stVerticalBlockBorderWrapper"]:hover { background: var(--bg-2) !important; border-color: var(--accent-line) !important; transform: translateY(-2px) !important; box-shadow: var(--shadow-lift), var(--glow-accent) !important; }
/* 29h. Code, sources, artifacts — depth without noise. */
div[data-testid="stChatMessageContent"] pre { background: #0d0d14 !important; border-color: var(--border) !important; box-shadow: var(--shadow-subtle), var(--inner-hi) !important; }
div[data-testid="stChatMessageContent"] thead th { background: var(--bg-2) !important; }
.poka-source { background: var(--bg-2) !important; border: 1px solid var(--border) !important; }
.poka-source:hover { border-color: var(--border-strong) !important; }
.poka-source-n { background: var(--accent-wash) !important; color: #c9c0ff !important; }
.poka-art { background: var(--bg-1) !important; box-shadow: var(--shadow-subtle) !important; }
.typing-indicator { background: var(--bg-1) !important; border: 1px solid var(--border) !important; box-shadow: var(--shadow-subtle) !important; }
section[data-testid="stMain"] .poka-empty { border-style: dashed !important; }
/* 30. VIBRANCY + DECONGEST (design only, zero features). Fixes the dull /
    cramped look from the screenshot: brighter layered surfaces, visible
    accent actions, airier sidebar + hero + composer. Purely additive:
    later position wins; no selector, key, class, or behavior removed. */
:root {
    --bg-0: #131318; --bg-1: #0e0e14; --bg-2: #1f1f2a; --bg-3: #2a2a38;
    --border: #2a2a38; --border-strong: #45455a;
    --text-1: #ffffff; --text-2: #c5c5d2;
    --accent: #7c6cff; --accent-hover: #8e7dff;
    --accent-wash: rgba(124, 108, 255, 0.16);
    --accent-line: rgba(124, 108, 255, 0.45);
}
/* 30a. Page + sidebar separation (wider rail = no more cramped [4,1] rows). */
.stApp {
    background:
        radial-gradient(1100px 480px at 50% -8%, rgba(124, 108, 255, 0.14), transparent 62%),
        radial-gradient(760px 400px at 88% 10%, rgba(80, 140, 255, 0.07), transparent 60%),
        var(--bg-0) !important;
}
section[data-testid="stSidebar"] { width: 280px !important; background: var(--bg-1) !important; border-right: 1px solid var(--border) !important; }
section[data-testid="stSidebar"] .block-container { padding: 16px 14px 20px !important; }
section[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] { gap: var(--sp-8) !important; }
section[data-testid="stSidebar"] .section-label { display: block !important; margin: 22px 0 8px !important; padding: 0 6px !important; color: #a8a8b8 !important; font-size: 11px !important; }
section[data-testid="stSidebar"] .poka-divider { margin: 16px 0 !important; background: var(--border) !important; opacity: 1 !important; }
section[data-testid="stSidebar"] div[data-testid="stCaptionContainer"] { word-break: break-word !important; white-space: normal !important; line-height: 1.5 !important; }
/* 30b. Actions you can actually see: violet New chat + send, visible plus. */
section[data-testid="stSidebar"] .st-key-new-chat button,
section[data-testid="stSidebar"] div[data-testid="stBaseButton-primary"] > button,
section[data-testid="stSidebar"] div[data-testid="stButton"] > button[kind="primary"] { background: linear-gradient(135deg, #7c6cff 0%, #9d8cff 100%) !important; background-color: #7c6cff !important; border: 1px solid rgba(163,148,255,0.55) !important; color: #fff !important; font-weight: 700 !important; box-shadow: 0 4px 18px rgba(124,108,255,0.35) !important; width: 100% !important; text-align: center !important; justify-content: center !important; border-radius: 12px !important; min-height: 42px !important; }
section[data-testid="stSidebar"] .st-key-new-chat button:hover { filter: brightness(1.08) !important; }
section[data-testid="stMain"] .st-key-composer { background: rgba(31, 31, 42, 0.92) !important; background-color: rgba(31, 31, 42, 0.92) !important; border: 1px solid var(--border-strong) !important; border-radius: 26px !important; box-shadow: 0 16px 44px rgba(0,0,0,0.55) !important; }
section[data-testid="stMain"] .st-key-composer:focus-within { border-color: var(--accent) !important; box-shadow: 0 0 0 3px var(--accent-wash), 0 0 28px rgba(124,108,255,0.3) !important; }
section[data-testid="stMain"] .st-key-composer [data-testid="column"]:first-child button { background: var(--bg-3) !important; background-color: var(--bg-3) !important; border: 1px solid var(--border-strong) !important; color: #fff !important; }
section[data-testid="stMain"] .st-key-composer .st-key-composer_send button,
section[data-testid="stMain"] .st-key-composer [data-testid="column"]:last-child button { background: linear-gradient(135deg, #7c6cff 0%, #a394ff 100%) !important; background-color: #7c6cff !important; border: 1px solid rgba(163,148,255,0.6) !important; box-shadow: 0 4px 16px rgba(124,108,255,0.45) !important; }
section[data-testid="stMain"] .st-key-composer .st-key-composer_send button::after,
section[data-testid="stMain"] .st-key-composer [data-testid="column"]:last-child button::after { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='white' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M8 13.5v-11M3.5 7.5L8 3l4.5 4.5'/%3E%3C/svg%3E") !important; }
/* 30c. Hero breathing room — subtitle never kisses the cards. */
.poka-home { padding-top: 56px !important; }
.poka-home p { color: var(--text-2) !important; margin: 12px auto 28px !important; font-size: var(--fs-15) !important; }
/* 30d. Cards with real surface + readable subtitles, no arrow collisions. */
.st-key-home [data-testid="stHorizontalBlock"] { gap: var(--sp-12) !important; }
.st-key-home div[data-testid="stVerticalBlockBorderWrapper"] { background: linear-gradient(180deg, #1b1b27 0%, #14141c 100%) !important; border: 1px solid var(--border) !important; border-radius: 14px !important; padding: 16px !important; min-height: 92px !important; }
.st-key-home div[data-testid="stVerticalBlockBorderWrapper"]:hover { border-color: var(--accent-line) !important; background: linear-gradient(180deg, #22222f 0%, #17171f 100%) !important; transform: translateY(-2px) !important; box-shadow: 0 12px 32px rgba(0,0,0,0.45), 0 0 24px rgba(124,108,255,0.18) !important; }
.st-key-home div[class*="st-key-suggest-"] button { color: #fff !important; padding-right: 30px !important; }
.st-key-home div[class*="st-key-suggest-"] button::before { opacity: 1 !important; }
.st-key-home div[class*="st-key-suggest-"] button::after { right: 12px !important; color: #8e8e9a !important; }
.st-key-home div[data-testid="stCaptionContainer"] { color: #a0a0b0 !important; padding-left: 32px !important; margin-top: 4px !important; }
/* 30e. Sidebar rows: full-width, brighter hover, accent active stays. */
section[data-testid="stSidebar"] div[data-testid="stButton"] > button:not(:disabled),
section[data-testid="stSidebar"] div[data-testid="stBaseButton-secondary"] > button:not(:disabled),
section[data-testid="stSidebar"] .stButton > button:not(:disabled) { background: transparent !important; border: 1px solid transparent !important; border-radius: 10px !important; min-height: 38px !important; color: #e8e8ee !important; }
section[data-testid="stSidebar"] div[data-testid="stButton"] > button:not(:disabled):hover { background: var(--bg-2) !important; border-color: var(--border-strong) !important; }
section[data-testid="stSidebar"] div.st-key-chat-search input { background: var(--bg-2) !important; border: 1px solid var(--border) !important; color: #fff !important; }
section[data-testid="stSidebar"] .poka-model { width: 100% !important; background: var(--bg-2) !important; border: 1px solid var(--border) !important; border-radius: 10px !important; padding: 8px 12px !important; }
/* 31. TIDY LAYOUT (design only, zero features). Fixes the messy /
    overlapping rows seen in chat: narrow pill buttons, squeezed
    time+Edit / Regenerate actions, wrapped sidebar texts. Purely
    additive; no selector, key, class, or behavior removed. */
/* 31a. Sidebar wrappers go full-width so pills become calm full rows. */
section[data-testid="stSidebar"] div[data-testid="stButton"],
section[data-testid="stSidebar"] div[data-testid="stBaseButton-secondary"],
section[data-testid="stSidebar"] div[data-testid="stBaseButton-primary"],
section[data-testid="stSidebar"] .stButton,
section[data-testid="stSidebar"] div[data-testid="stDownloadButton"] { width: 100% !important; max-width: 100% !important; }
section[data-testid="stSidebar"] div[data-testid="stButton"] > button,
section[data-testid="stSidebar"] div[data-testid="stBaseButton-secondary"] > button,
section[data-testid="stSidebar"] .stButton > button { width: 100% !important; justify-content: flex-start !important; }
section[data-testid="stSidebar"] [data-testid="column"] { min-width: 0 !important; }
/* 31b. Sidebar texts wrap cleanly instead of clipping mid-word. */
section[data-testid="stSidebar"] .poka-empty { white-space: normal !important; text-wrap: pretty !important; line-height: 1.55 !important; padding: 2px 6px !important; }
section[data-testid="stSidebar"] div[data-testid="stCaptionContainer"] { overflow-wrap: anywhere !important; }
/* 31c. Turn spacing — airy, one idea per row. */
section[data-testid="stMain"] div[data-testid="stChatMessage"] { margin: 0 0 28px !important; padding-top: 0 !important; }
/* 31d. User action row: full-width, right-clustered, below the bubble. */
section[data-testid="stMain"] div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]) [data-testid="stHorizontalBlock"] { width: 100% !important; justify-content: flex-end !important; gap: 6px !important; margin-top: 6px !important; }
section[data-testid="stMain"] div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]) [data-testid="column"] { flex: 0 1 auto !important; min-width: 0 !important; width: auto !important; }
section[data-testid="stMain"] div[class*="st-key-edit-"] button { background: transparent !important; background-color: transparent !important; border: 1px solid transparent !important; box-shadow: none !important; color: var(--text-3) !important; }
section[data-testid="stMain"] div[class*="st-key-edit-"] button:hover { color: var(--text-1) !important; border-color: var(--border-strong) !important; background: var(--bg-2) !important; }
/* 31e. Assistant action: ghost Regenerate with breathing room. */
section[data-testid="stMain"] div[class*="st-key-regen-msg-"] button { background: transparent !important; background-color: transparent !important; border: 1px solid transparent !important; box-shadow: none !important; color: var(--text-3) !important; margin-top: 6px !important; }
section[data-testid="stMain"] div[class*="st-key-regen-msg-"] button:hover { color: var(--text-1) !important; border-color: var(--border-strong) !important; background: var(--bg-2) !important; }
/* 31f. Meta timestamps stay tiny and never push buttons around. */
section[data-testid="stMain"] .poka-meta { min-height: 0 !important; margin: 6px 0 0 !important; }
section[data-testid="stMain"] .poka-time { font-size: 11px !important; }
/* 31g. Live slot reserves the above-composer position for in-flight
    turns; empty (the common case) it collapses to nothing. */
.st-key-live-response:empty { display: none !important; }
/* 32. BUBBLE RESET (design only, zero features). One authoritative rule
    per turn type so padding/line-height/width can never collapse or clip
    glyphs no matter which earlier override wins the cascade. Purely
    additive; no selector, key, class, or behavior removed. */
section[data-testid="stMain"] div[data-testid="stChatMessage"] { overflow: visible !important; scroll-margin: 24px 0 !important; }
section[data-testid="stMain"] div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]) div[data-testid="stChatMessageContent"] {
    display: block !important; width: fit-content !important; max-width: min(70%, 480px) !important;
    height: auto !important; min-height: 0 !important; max-height: none !important;
    margin-left: auto !important; margin-right: 0 !important;
    padding: 12px 18px !important; overflow: visible !important; white-space: normal !important;
    overflow-wrap: break-word !important; word-break: break-word !important;
    font-size: var(--fs-15) !important; line-height: 1.65 !important;
    border-radius: 18px !important;
}
section[data-testid="stMain"] div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarAssistant"]) div[data-testid="stChatMessageContent"] {
    display: block !important; width: 100% !important; max-width: 100% !important;
    height: auto !important; min-height: 0 !important; max-height: none !important;
    padding: var(--sp-16) var(--sp-20) !important; overflow: visible !important; white-space: normal !important;
    font-size: var(--fs-15) !important; line-height: 1.7 !important;
}
section[data-testid="stMain"] div[data-testid="stChatMessageContent"] p { overflow: visible !important; max-height: none !important; }
/* 33. TURN LAYOUT TAKEOVER (design only, zero features). Streamlit's
    default chat row is flex (content is flex-grow:1 + margin:auto), which
    stretches bubbles and makes fresh nodes paint clipped mid-layout.
    Take full control: plain block turns, explicit margins, hugging user
    bubbles, no entrance animation on turns. Purely additive; no
    selector, key, class, or behavior removed. */
section[data-testid="stMain"] div[data-testid="stChatMessage"] {
    display: block !important;
    background: transparent !important; background-color: transparent !important;
    border: none !important; box-shadow: none !important;
    padding: 0 !important; gap: 0 !important;
    align-items: normal !important;
}
section[data-testid="stMain"] div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]) div[data-testid="stChatMessageContent"] {
    flex: none !important; flex-grow: 0 !important; flex-shrink: 1 !important;
    margin-top: 0 !important; margin-bottom: 0 !important;
    animation: none !important;
}
section[data-testid="stMain"] div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarAssistant"]) div[data-testid="stChatMessageContent"] {
    flex: none !important;
    margin: 0 !important;
    animation: none !important;
}
"""


def apply_theme() -> None:
    """Inject the Poka theme into the page."""
    st.markdown(
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700'
        "&family=Space+Grotesk:wght@500;600;700"
        "&family=JetBrains+Mono:wght@400;500&display=swap\" rel=\"stylesheet\">",
        unsafe_allow_html=True,
    )
    st.markdown("<style>" + THEME_CSS + "</style>", unsafe_allow_html=True)
