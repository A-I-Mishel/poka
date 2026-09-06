"""Polish layer — fills every unstyled class + fixes layout alignment.

Covers all `class="poka-*"` / `project-card-*` / `msg-*` hooks emitted by
app.py + ui/*.py that had no CSS definition, plus:
- composer dock centering with the sidebar open (desktop) / full-width (mobile)
- main content bottom padding so the fixed dock never covers messages
- modern Streamlit main selector (`.main .block-container` is legacy)
- duplicate section-header consolidation (section-label == sidebar-section-title)
- home hero + suggestion cards, brand row, dividers, chips, menus,
  file rows, memory rows, artifact cards, meta rows, copy buttons.
Visual-only. No widget keys, no behavior changes. Every value references
a token from ui/theme/tokens.py (exposed as CSS vars in base.py).
"""

POLISH_CSS: str = """
/* ---------- Brand ---------- */
.poka-brand { display: flex; align-items: center; gap: var(--space-sm-plus); padding: var(--space-xs) var(--space-xxxs) var(--space-xxxs); }
.poka-mark { width: var(--brand-mark-size); height: var(--brand-mark-size); border-radius: var(--radius-md); display: inline-flex; align-items: center; justify-content: center; background: linear-gradient(135deg, var(--accent-primary), var(--accent-primary-deep)); color: var(--text-primary); flex-shrink: 0; box-shadow: var(--shadow-glow); }
.poka-mark svg { fill: currentColor; }
.poka-brand-text { display: flex; flex-direction: column; line-height: var(--leading-compact); }
.poka-word { font-size: var(--font-lg); font-weight: var(--weight-bold); color: var(--text-primary); letter-spacing: var(--tracking-snug); }
.poka-sub { font-size: var(--font-xs); color: var(--text-muted); font-weight: var(--weight-medium); }
.brand-title { font-size: var(--font-xxxl); font-weight: var(--weight-bold); color: var(--text-primary); letter-spacing: var(--tracking-tight); margin: 0; }

.poka-divider { height: var(--line); background: var(--border-subtle); margin: var(--space-md-plus) 0 var(--space-xs); }
.poka-match { font-size: var(--font-xs); color: var(--text-muted); margin: var(--space-xs) var(--space-xxxs) 0; }
.poka-card-sub { font-size: var(--font-xs); font-weight: var(--weight-semibold); text-transform: uppercase; letter-spacing: var(--tracking-wide); color: var(--text-muted); margin: var(--space-md-plus) 0 var(--space-xxs); }
.poka-empty { font-size: var(--font-sm); color: var(--text-muted); line-height: var(--leading-normal); margin: var(--space-xxs) 0; padding: var(--space-md); text-align: center; border: var(--line) dashed var(--border-default); border-radius: var(--radius-md); background: transparent; }

/* ---------- Section headers (single visual) ---------- */
.section-label, .sidebar-section-title { color: var(--text-muted); font-size: var(--font-tiny); text-transform: uppercase; letter-spacing: var(--tracking-wider); font-weight: var(--weight-semibold); margin: var(--space-xl) 0 var(--space-xxs); }
.section-label + .sidebar-section-title, .sidebar-section-title + .section-label { display: none; }
p.section-label, p.sidebar-section-title { margin: var(--space-xl) 0 var(--space-xxs); }

/* ---------- Home hero ---------- */
.poka-home { text-align: center; padding: var(--space-xxxl) var(--space-xl-minus) var(--space-lg-plus); max-width: var(--composer-max-width); margin: 0 auto; animation: fadeIn var(--anim-normal) var(--anim-easing) both; }
.poka-home-mark { width: var(--hero-mark-size); height: var(--hero-mark-size); border-radius: var(--radius-lg); display: inline-flex; align-items: center; justify-content: center; background: linear-gradient(135deg, var(--accent-primary), var(--accent-primary-deep)); color: var(--text-primary); box-shadow: var(--shadow-glow); margin-bottom: var(--space-md-plus); }
.poka-home-mark svg { fill: currentColor; }
.poka-eyebrow { font-size: var(--font-xs); font-weight: var(--weight-semibold); text-transform: uppercase; letter-spacing: var(--tracking-widest); color: var(--accent-primary-hover); margin: 0 0 var(--space-sm); }
.poka-home h1 { font-size: clamp(var(--hero-h-min), 4vw, var(--hero-h-max)); font-weight: var(--weight-bold); letter-spacing: var(--tracking-tight); color: var(--text-primary); margin: 0 0 var(--space-sm); }
.poka-home p:last-child { font-size: var(--font-sm); color: var(--text-secondary); margin: 0; line-height: var(--leading-normal); }

/* Suggestion cards (st-key-home) */
.st-key-home { max-width: var(--home-max-width); margin: 0 auto; }
.st-key-home div[data-testid="stVerticalBlockBorderWrapper"] { background: var(--bg-elevated); border: var(--line) solid var(--border-subtle); border-radius: var(--radius-lg); padding: var(--space-md) var(--space-md-plus); transition: border-color var(--anim-fast) var(--anim-easing), transform var(--anim-fast) var(--anim-easing); }
.st-key-home div[data-testid="stVerticalBlockBorderWrapper"]:hover { border-color: var(--border-accent); transform: translateY(calc(var(--line) * -1)); }
.st-key-home .stButton > button { background: transparent !important; border: none !important; padding: 0 !important; font-size: var(--font-sm) !important; font-weight: var(--weight-semibold) !important; color: var(--text-primary) !important; text-align: left !important; width: auto !important; min-height: 0 !important; }
.st-key-home .stCaption { color: var(--text-muted); }

/* ---------- Project cards ---------- */
.project-card { margin: var(--space-xxs) 0 var(--space-xxxs); }
.project-card-info { display: flex; flex-direction: column; min-width: 0; line-height: var(--leading-card); }
.project-card-title { font-size: var(--font-sm); font-weight: var(--weight-semibold); color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.project-card-meta { font-size: var(--font-xs); color: var(--text-muted); }
.project-card-icon { font-size: var(--font-sm); font-weight: var(--weight-bold); flex-shrink: 0; }

/* Tighten the button row that follows each visual card so card + action read as one unit */
div[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] { gap: var(--space-xxs); }

/* ---------- Composer dock: sidebar-aware centering ---------- */
section[data-testid="stMain"] .block-container { max-width: var(--content-max-width) !important; margin: 0 auto !important; padding-bottom: var(--chat-bottom-pad) !important; }
.composer-dock, .st-key-composer-dock { left: calc(50% + var(--sidebar-width) / 2); width: min(var(--composer-max-width), calc(100% - var(--space-xxl) - var(--sidebar-width))); }
.composer-dock:empty, .st-key-composer-dock:empty { display: none; }
@media (max-width: 1200px) { .composer-dock, .st-key-composer-dock { left: 50%; width: min(var(--composer-max-width), calc(100% - var(--space-xxl))); } }
@media (max-width: 768px) { .composer-dock, .st-key-composer-dock { left: 50%; width: calc(100% - var(--space-xl)); bottom: var(--space-md); border-radius: var(--radius-full); padding: var(--space-sm) var(--space-sm-plus); } }

/* Composer inner controls: one row, one height, one language.
   Per-key descendant selectors (Streamlit nests wrappers between the
   st-key-* container and the button, so no child combinators). */
.st-key-composer div[data-testid="stTextInput"] input { background: transparent !important; border: none !important; box-shadow: none !important; font-size: var(--font-sm) !important; padding: var(--space-sm) var(--space-xs) !important; min-height: var(--composer-control-size) !important; }
.st-key-composer div[data-testid="stTextInput"] input:focus { border: none !important; box-shadow: none !important; }
.st-key-composer .stButton button { display: inline-flex !important; align-items: center !important; justify-content: center !important; font-weight: var(--weight-semibold) !important; min-height: var(--composer-control-size) !important; height: var(--composer-control-size) !important; padding-top: 0 !important; padding-bottom: 0 !important; }
/* Icon buttons: true circles */
.st-key-composer .st-key-composer_plus button, .st-key-composer .st-key-composer_send button { width: var(--composer-control-size) !important; padding-left: 0 !important; padding-right: 0 !important; border-radius: var(--radius-full) !important; }
/* Plus: plain ghost glyph, no chrome (reference: bare +) */
.st-key-composer .st-key-composer_plus button { background: transparent !important; border: none !important; box-shadow: none !important; color: var(--text-secondary) !important; font-size: var(--font-xl) !important; font-weight: var(--weight-regular) !important; }
.st-key-composer .st-key-composer_plus button:hover { color: var(--text-primary) !important; }
/* Mode: borderless ghost label on the right (reference: Think) */
.st-key-composer .st-key-composer-mode button { width: auto !important; padding-left: var(--space-sm) !important; padding-right: var(--space-sm) !important; border-radius: var(--radius-full) !important; font-size: var(--font-sm) !important; font-weight: var(--weight-medium) !important; background: transparent !important; border: none !important; box-shadow: none !important; color: var(--text-secondary) !important; white-space: nowrap !important; }
.st-key-composer .st-key-composer-mode button:hover { color: var(--accent-primary-hover) !important; }
/* Send: primary gradient circle */
.st-key-composer .st-key-composer_send button { background: linear-gradient(135deg, var(--accent-primary), var(--accent-primary-deep)) !important; border: none !important; color: var(--text-primary) !important; font-size: var(--font-lg) !important; box-shadow: var(--shadow-avatar-bot) !important; }
button[kind="secondary"] { width: auto; }

/* ---------- Chat: meta / copy / search-hit ---------- */
.poka-meta { display: flex; align-items: center; gap: var(--space-sm); margin-top: var(--space-sm); }
.poka-time { font-size: var(--font-tiny); color: var(--text-muted); }
.poka-copy, .poka-code-copy, .poka-listen { background: var(--overlay-ghost); border: var(--line) solid var(--border-default); border-radius: var(--radius-sm); color: var(--text-muted); padding: var(--space-xxxs) var(--space-sm-plus); font-size: var(--font-tiny); cursor: pointer; transition: all var(--anim-fast) var(--anim-easing); font-family: var(--font-stack); }
.poka-copy:hover, .poka-code-copy:hover, .poka-listen:hover { background: var(--overlay-ghost-hover); color: var(--text-secondary); }
div[data-testid="stChatMessageContent"] pre { position: relative; }
.poka-code-copy { position: absolute; top: var(--space-sm); right: var(--space-sm); opacity: 0; }
div[data-testid="stChatMessageContent"] pre:hover .poka-code-copy { opacity: 1; }
mark.search-hit { background: var(--mark-hit); color: inherit; border-radius: var(--space-xxxs); padding: 0 var(--space-xxxs); }
.poka-assistant-id { display: flex; align-items: center; gap: var(--space-xxs); font-size: var(--font-xs); font-weight: var(--weight-semibold); color: var(--text-secondary); margin-bottom: var(--space-xxs); }
.poka-assistant-mark { width: var(--assistant-mark-size); height: var(--assistant-mark-size); border-radius: var(--radius-sm); display: inline-flex; align-items: center; justify-content: center; background: linear-gradient(135deg, var(--accent-primary), var(--accent-primary-deep)); color: var(--text-primary); }
.poka-assistant-mark svg { fill: currentColor; }
.typing-indicator { display: inline-flex; gap: var(--space-xs); align-items: center; padding: var(--space-md) var(--space-xs); color: var(--text-muted); font-size: var(--font-sm); }
.typing-indicator span:not(.typing-label) { width: var(--space-xxs); height: var(--space-xxs); border-radius: var(--radius-full); background: var(--accent-primary); animation: thinkingBounce var(--anim-thinking) ease-in-out infinite both; }
.typing-indicator span:nth-child(2) { animation-delay: 0.15s; }
.typing-indicator span:nth-child(3) { animation-delay: 0.3s; }
.typing-label { margin-left: var(--space-xxs); }

/* Assistant markdown inside legacy bubbles should not add extra outer margins */
.msg-bubble-assistant p:first-child { margin-top: 0; }
.msg-bubble-assistant p:last-child { margin-bottom: 0; }
.msg-bubble-assistant pre { background: var(--bg-code); border: var(--line) solid var(--overlay-line-ghost); border-radius: var(--radius-md); padding: var(--space-md) var(--space-md-plus); overflow-x: auto; font-family: var(--font-mono); font-size: var(--font-code); }
.msg-bubble-assistant code { font-family: var(--font-mono); font-size: var(--font-code); }
.msg-bubble-assistant table { width: 100%; border-collapse: collapse; font-size: var(--font-sm); }
.msg-bubble-assistant th, .msg-bubble-assistant td { border: var(--line) solid var(--border-subtle); padding: var(--space-xxs) var(--space-sm-plus); text-align: left; }

/* ---------- Chips / pills ---------- */
.poka-chips { display: flex; flex-wrap: wrap; gap: var(--space-xxs); }
.poka-chip { display: inline-flex; align-items: center; gap: var(--space-sm); background: var(--bg-surface); border: var(--line) solid var(--border-default); border-radius: var(--radius-full); padding: var(--space-xs) var(--space-xxs) var(--space-xs) var(--space-sm-plus); font-size: var(--font-xs); color: var(--text-primary); max-width: 100%; }
.poka-chip-icon { display: inline-flex; color: var(--accent-primary-hover); }
.poka-chip-icon svg { fill: none; }
.poka-chip-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: var(--chip-name-max); }
.poka-search-pill { display: inline-flex; align-items: center; gap: var(--space-xxs); background: var(--accent-primary-glow); border: var(--line) solid var(--border-accent); color: var(--accent-primary-hover); border-radius: var(--radius-full); padding: var(--space-xs) var(--space-md); font-size: var(--font-xs); font-weight: var(--weight-medium); }
.poka-search-mark { display: inline-flex; }
.poka-search-mark svg { fill: currentColor; }
.composer-chips:empty, .st-key-composer-chips:empty { display: none; }
.composer-chips .poka-chips, .st-key-composer-chips .poka-chips { margin-bottom: var(--space-xxs); }

/* ---------- Attachment menu ---------- */
.st-key-attachment-menu { background: var(--bg-elevated); border: var(--line) solid var(--border-default); border-radius: var(--radius-lg); padding: var(--space-md) var(--space-md-plus); margin: var(--space-sm) 0; box-shadow: var(--shadow-md); }
.poka-menu-head { font-size: var(--font-xs); font-weight: var(--weight-semibold); text-transform: uppercase; letter-spacing: var(--tracking-wide); color: var(--text-muted); margin: var(--space-sm) 0 var(--space-xxs); }
.poka-menu-head:first-child { margin-top: 0; }
.poka-menu-sub { font-size: var(--font-xs); color: var(--text-muted); margin: var(--space-xs) 0 var(--space-sm); }

/* ---------- File rows ---------- */
.poka-msg-file { margin-bottom: var(--space-sm); }
.poka-file-row { display: flex; align-items: center; gap: var(--space-sm-plus); background: var(--bg-surface); border: var(--line) solid var(--border-subtle); border-radius: var(--radius-md); padding: var(--space-sm) var(--space-md-plus); }
.poka-file-icon { display: inline-flex; color: var(--accent-primary-hover); flex-shrink: 0; }
.poka-file-name { font-size: var(--font-sm); color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.poka-file-sub { font-size: var(--font-xs); color: var(--text-muted); margin: var(--space-xxxs) var(--line) var(--space-sm); }

/* ---------- Memory vault ---------- */
.poka-mem-row { background: var(--bg-elevated); border: var(--line) solid var(--border-subtle); border-radius: var(--radius-md); padding: var(--space-sm-plus) var(--space-md); margin-bottom: var(--space-sm); }
.poka-mem-head { display: flex; align-items: center; gap: var(--space-sm); margin-bottom: var(--space-xs); }
.poka-mem-type { font-size: var(--font-xs); font-weight: var(--weight-semibold); color: var(--accent-primary-hover); text-transform: uppercase; letter-spacing: var(--tracking-wide); }
.poka-mem-src { font-size: var(--font-tiny); color: var(--text-muted); background: var(--bg-surface); border: var(--line) solid var(--border-subtle); border-radius: var(--radius-full); padding: var(--line) var(--space-sm); }
.poka-mem-val { font-size: var(--font-sm); color: var(--text-primary); line-height: var(--leading-normal); overflow-wrap: anywhere; }
.poka-mem-date { font-size: var(--font-tiny); color: var(--text-muted); margin-top: var(--space-xs); }

/* ---------- Artifact cards ---------- */
.poka-art { display: flex; align-items: center; gap: var(--space-sm-plus); background: var(--bg-elevated); border: var(--line) solid var(--border-subtle); border-radius: var(--radius-md); padding: var(--space-sm-plus) var(--space-md); margin: var(--space-sm) 0 var(--space-xs); }
.poka-art-expired { opacity: var(--opacity-disabled); }
.poka-art-icon { width: var(--artifact-icon-size); height: var(--artifact-icon-size); border-radius: var(--radius-md); display: inline-flex; align-items: center; justify-content: center; background: var(--accent-primary-glow); border: var(--line) solid var(--border-accent); color: var(--accent-primary-hover); flex-shrink: 0; }
.poka-art-text { display: flex; flex-direction: column; min-width: 0; }
.poka-art-name { font-size: var(--font-sm); font-weight: var(--weight-semibold); color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.poka-art-sub { font-size: var(--font-xs); color: var(--text-muted); }

/* ---------- Sources (extend legacy) ---------- */
.poka-sources { background: var(--bg-elevated); border: var(--line) solid var(--border-subtle); border-radius: var(--radius-md); padding: var(--space-sm-plus) var(--space-md); margin: var(--space-sm) 0; }
.poka-sources-head { margin: 0 0 var(--space-xxs); }
.poka-source { font-size: var(--font-sm); margin: var(--space-xs) 0; color: var(--text-secondary); }

/* ---------- Account / model ---------- */
.poka-model { display: flex; align-items: center; gap: var(--space-sm); padding: var(--space-xxs) var(--space-xxxs); }
.poka-dot { width: var(--space-sm); height: var(--space-sm); border-radius: var(--radius-full); flex-shrink: 0; }
.poka-dot-online { background: var(--accent-success); box-shadow: 0 0 var(--space-sm) var(--accent-success-glow); }
.poka-dot-offline { background: var(--text-muted); }
.poka-model-name { font-size: var(--font-sm); font-weight: var(--weight-medium); color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* ---------- Sidebar buttons: full-width quiet rows, one height ----------
   Verified DOM (Streamlit 1.63): the button itself carries
   button[data-testid="stBaseButton-*"]; its wrapper is div#stButton when
   the widget has no help text, or span#stTooltipHoverTarget when it does.
   Both wrappers become flex so the button can fill them. */
section[data-testid="stSidebar"] div[data-testid="stButton"],
section[data-testid="stSidebar"] div[data-testid="stButton"] > div:first-child,
section[data-testid="stSidebar"] span[data-testid="stTooltipIcon"],
section[data-testid="stSidebar"] span[data-testid="stTooltipHoverTarget"],
section[data-testid="stSidebar"] div[data-testid="stDownloadButton"] { display: flex !important; flex: 1 1 auto !important; width: 100% !important; max-width: 100% !important; }
/* Stretch the whole ancestor chain: Streamlit shrink-wraps element
   containers in the rail, so buttons cannot fill what ancestors deny. */
section[data-testid="stSidebar"] div[data-testid="stElementContainer"] { width: 100% !important; max-width: 100% !important; align-self: stretch !important; }
section[data-testid="stSidebar"] div[data-testid="stButton"] > button,
section[data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"],
section[data-testid="stSidebar"] div[data-testid="stDownloadButton"] > button { flex: 1 1 auto !important; width: 100% !important; min-height: var(--btn-min-height); text-align: left !important; font-size: var(--font-sm); font-weight: var(--weight-medium); justify-content: flex-start !important; }
section[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"] { flex: 1 1 auto !important; width: 100% !important; min-height: var(--btn-min-height); }
section[data-testid="stSidebar"] .st-key-new-chat button { text-align: center !important; justify-content: center !important; }
/* Project row: Personal and the + square share one height so they read as a pair */
section[data-testid="stSidebar"] .st-key-project-personal button,
section[data-testid="stSidebar"] .st-key-project-create button { min-height: var(--btn-min-height); }
/* Search field breathing room */
section[data-testid="stSidebar"] div[data-testid="stTextInput"] { margin-bottom: var(--space-xs); }

/* ---------- Live response spacing ---------- */
.st-key-live-response { margin-bottom: var(--space-sm); }

/* ---------- Legacy split-wrapper safety ----------
   Message rows/bubbles used to be emitted as open/close tags in separate
   st.markdown calls; browsers auto-close those, leaving empty boxes. The
   renderers now use the native chat layout, but these guards keep any
   leftover empties (and their Streamlit containers) from taking space. */
.msg-row:empty, .msg-row-user:empty,
.msg-bubble-user:empty, .msg-bubble-assistant:empty { display: none !important; margin: 0 !important; padding: 0 !important; border: none !important; }
div[data-testid="stMarkdownContainer"]:has(> .msg-row:empty),
div[data-testid="stMarkdownContainer"]:has(> .msg-row-user:empty),
div[data-testid="stMarkdownContainer"]:has(> .msg-bubble-user:empty),
div[data-testid="stMarkdownContainer"]:has(> .msg-bubble-assistant:empty) { display: none !important; margin: 0 !important; padding: 0 !important; min-height: 0 !important; }
/* Legacy custom avatars (replaced by native orb avatars) take no space */
.msg-avatar-wrap, .msg-avatar-user { display: none !important; }
div[data-testid="stMarkdownContainer"]:has(> .msg-avatar-wrap),
div[data-testid="stMarkdownContainer"]:has(> .msg-avatar-user) { display: none !important; margin: 0 !important; padding: 0 !important; min-height: 0 !important; }

/* Native bubble inner polish */
div[data-testid="stChatMessageContent"] p { overflow-wrap: anywhere; }
div[data-testid="stChatMessageContent"] img { border-radius: var(--radius-md); max-width: 100%; }
div[data-testid="stChatMessageContent"] pre { background: var(--bg-code); border: var(--line) solid var(--overlay-line-ghost); border-radius: var(--radius-md); padding: var(--space-md) var(--space-md-plus); overflow-x: auto; font-family: var(--font-mono); font-size: var(--font-code); position: relative; }
div[data-testid="stChatMessageContent"] table { width: 100%; border-collapse: collapse; font-size: var(--font-sm); display: block; overflow-x: auto; }
div[data-testid="stChatMessageContent"] th, div[data-testid="stChatMessageContent"] td { border: var(--line) solid var(--border-subtle); padding: var(--space-xxs) var(--space-sm-plus); text-align: left; }
/* Action anchor inside the native bubble: quiet row, hover-revealed on desktop */
.msg-actions { display: flex; gap: var(--space-xxs); margin-top: var(--space-sm-plus); min-height: 0; }
.msg-actions:empty { margin-top: 0; }
div[data-testid="stChatMessageContent"] .msg-actions { opacity: 0; transition: opacity var(--anim-fast) var(--anim-easing); }
div[data-testid="stChatMessage"]:hover div[data-testid="stChatMessageContent"] .msg-actions { opacity: 1; }
@media (hover: none) { div[data-testid="stChatMessageContent"] .msg-actions { opacity: 1; } }

/* ---------- Narrow screens ---------- */
@media (max-width: 480px) {
  .poka-home { padding: var(--space-xxl) var(--space-md) var(--space-md); }
  .msg-row, .msg-row-user { max-width: 100%; }
  .msg-bubble-assistant { max-width: 100%; }
  .msg-bubble-user { max-width: 88%; }
  .poka-chip-name { max-width: var(--chip-name-max-mobile); }
}
"""
