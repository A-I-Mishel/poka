"""Chat theme layer — messages, avatars, bubbles, code, thinking, skeleton."""

CHAT_CSS: str = '''
/* Native chat avatars as gradient orbs (Streamlit owns the layout, so
   avatar + content stay correctly side-by-side on every version).
   NOTE (verified against the installed Streamlit frontend bundle):
   default avatars render stChatMessageAvatarUser / Assistant testids,
   while custom emoji avatars (e.g. the brand spark) render with NO avatar
   testid — so the orb + bubble below are structural and avatar-agnostic,
   with the User testid only used for the user override. */
div[data-testid="stChatMessage"] > div:not([data-testid="stChatMessageContent"]) { display: flex !important; align-items: center !important; justify-content: center !important; width: var(--avatar-size) !important; height: var(--avatar-size) !important; border-radius: var(--radius-full) !important; flex-shrink: 0 !important; color: var(--text-primary) !important; font-size: var(--font-xs) !important; font-weight: var(--weight-bold) !important; background: linear-gradient(135deg, var(--accent-primary), var(--accent-primary-deep)) !important; box-shadow: var(--shadow-glow) !important; }
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]) > div:not([data-testid="stChatMessageContent"]) { background: linear-gradient(135deg, var(--accent-secondary), var(--accent-secondary-deep)) !important; box-shadow: var(--shadow-avatar-user) !important; }
div[data-testid="stChatMessageAvatarAssistant"] { background: linear-gradient(135deg, var(--accent-primary), var(--accent-primary-deep)) !important; box-shadow: var(--shadow-glow) !important; }
div[data-testid="stChatMessageAvatarUser"] { background: linear-gradient(135deg, var(--accent-secondary), var(--accent-secondary-deep)) !important; box-shadow: var(--shadow-avatar-user) !important; }
div[data-testid="stChatMessage"] > div:not([data-testid="stChatMessageContent"]) svg { width: var(--font-sm) !important; height: var(--font-sm) !important; }

/* Native chat message layout: gap between avatar orb and bubble */
[data-testid="stChatMessage"] { background: transparent !important; border: none !important; padding: var(--space-xxs) 0 !important; margin: 0 auto !important; max-width: var(--chat-max-width) !important; gap: var(--space-sm-plus) !important; }
/* Assistant bubble = the native content box (default for every message,
   so custom-emoji avatars without a testid still get a bubble) */
div[data-testid="stChatMessage"] div[data-testid="stChatMessageContent"] { background: var(--bg-elevated) !important; border: var(--line) solid var(--border-default) !important; border-radius: var(--radius-lg) !important; padding: var(--space-md) var(--space-lg) !important; color: var(--text-primary) !important; overflow-wrap: anywhere !important; }
/* User bubble override: tinted, snug (default user avatar keeps its testid) */
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]) div[data-testid="stChatMessageContent"] { background: linear-gradient(135deg, var(--bubble-user-from), var(--bubble-user-to)) !important; border: var(--line) solid var(--border-accent) !important; border-radius: var(--radius-lg) !important; padding: var(--space-sm-plus) var(--space-md-plus) !important; color: var(--text-primary) !important; overflow-wrap: anywhere !important; }

/* Message row (legacy custom rows; native layout above is authoritative) */
.msg-row { display: flex; gap: var(--space-sm-plus); padding: var(--space-xxs) 0; align-items: flex-start; max-width: var(--chat-max-width); margin: 0 auto; }
.msg-row-user { display: flex; gap: var(--space-sm-plus); padding: var(--space-xxs) 0; align-items: flex-start; max-width: var(--chat-max-width); margin: 0 auto; flex-direction: row-reverse; }

/* Avatars (legacy custom avatars; native orbs above are authoritative) */
.msg-avatar-wrap { position: relative; flex-shrink: 0; width: var(--avatar-size); height: var(--avatar-size); }
.msg-avatar-bot { width: var(--avatar-size); height: var(--avatar-size); border-radius: var(--radius-full); background: linear-gradient(135deg, var(--accent-primary), var(--accent-primary-deep)); color: var(--text-primary); display: flex; align-items: center; justify-content: center; font-size: var(--font-xs); font-weight: var(--weight-bold); box-shadow: var(--shadow-avatar-bot); }
.msg-avatar-user { width: var(--avatar-size); height: var(--avatar-size); border-radius: var(--radius-full); background: linear-gradient(135deg, var(--accent-secondary), var(--accent-secondary-deep)); color: var(--text-primary); display: flex; align-items: center; justify-content: center; font-size: var(--font-xs); font-weight: var(--weight-semibold); box-shadow: var(--shadow-avatar-user); flex-shrink: 0; }
.msg-status { position: absolute; bottom: calc(var(--line) * -1); right: calc(var(--line) * -1); width: var(--space-sm); height: var(--space-sm); border-radius: var(--radius-full); background: var(--accent-success); border: calc(var(--line) * 2) solid var(--bg-base); }

/* Bubbles (legacy custom bubbles; native content bubbles above are authoritative) */
.msg-bubble-assistant { flex: 1; min-width: 0; max-width: var(--bubble-max-width); background: var(--bg-elevated); border: var(--line) solid var(--border-default); border-radius: var(--radius-lg); padding: var(--space-md) var(--space-lg); color: var(--text-primary); font-size: var(--font-sm); line-height: var(--leading-normal); overflow-wrap: anywhere; }
.msg-bubble-assistant:hover { border-color: var(--border-hover); }
.msg-bubble-user { max-width: 80%; background: linear-gradient(135deg, var(--bubble-user-from), var(--bubble-user-to)); border: var(--line) solid var(--border-accent); border-radius: var(--radius-lg); padding: var(--space-sm-plus) var(--space-md-plus); color: var(--text-primary); font-size: var(--font-sm); line-height: var(--leading-tight); box-shadow: var(--shadow-bubble-user); overflow-wrap: anywhere; }

/* Actions */
.msg-actions { display: flex; gap: var(--space-xxs); margin-top: var(--space-sm); opacity: 0; transition: opacity var(--anim-fast) var(--anim-easing); }
.msg-bubble-assistant:hover .msg-actions { opacity: 1; }
@media (hover: none) { .msg-actions { opacity: 1; } }
.msg-action-btn { background: var(--overlay-ghost); border: var(--line) solid var(--border-default); border-radius: var(--radius-sm); color: var(--text-muted); padding: var(--space-xs) var(--space-sm-plus); font-size: var(--font-tiny); cursor: pointer; transition: all var(--anim-fast) var(--anim-easing); }
.msg-action-btn:hover { background: var(--overlay-ghost-hover); color: var(--text-secondary); border-color: var(--border-hover); }

/* Code blocks */
.code-block { background: var(--bg-code); border: var(--line) solid var(--overlay-line-ghost); border-radius: var(--radius-md); overflow: hidden; margin: var(--space-sm-plus) 0; }
.code-header { display: flex; align-items: center; gap: var(--space-xxs); padding: var(--space-sm) var(--space-md); background: var(--overlay-ghost-faint); border-bottom: var(--line) solid var(--overlay-line-ghost); }
.code-dot { width: var(--space-sm-plus); height: var(--space-sm-plus); border-radius: var(--radius-full); }
.code-dot-red { background: var(--accent-error); }
.code-dot-yellow { background: var(--accent-warning); }
.code-dot-green { background: var(--accent-success); }
.code-lang { margin-left: auto; font-size: var(--font-tiny); color: var(--text-muted); font-family: var(--font-mono); }
.code-body { padding: var(--space-md) var(--space-lg); font-family: var(--font-mono); font-size: var(--font-code); color: var(--text-secondary); overflow-x: auto; white-space: pre; }

/* Thinking */
.thinking-dots { display: inline-flex; gap: var(--space-xs); align-items: center; padding: var(--space-md) var(--space-lg); }
.thinking-dots span { width: var(--space-sm); height: var(--space-sm); border-radius: var(--radius-full); background: var(--accent-primary); animation: thinkingBounce var(--anim-thinking) ease-in-out infinite both; }
.thinking-dots span:nth-child(2) { animation-delay: 0.15s; }
.thinking-dots span:nth-child(3) { animation-delay: 0.3s; }

/* Skeleton */
.skeleton-msg { display: flex; gap: var(--space-sm-plus); padding: var(--space-xxs) 0; max-width: var(--chat-max-width); margin: 0 auto; }
.skeleton-avatar { width: var(--avatar-size); height: var(--avatar-size); border-radius: var(--radius-full); background: linear-gradient(90deg, var(--bg-elevated) 25%, var(--overlay-shimmer-hi) 50%, var(--bg-elevated) 75%); background-size: 200% 100%; animation: shimmer var(--anim-shimmer) infinite; }
.skeleton-line { height: var(--space-sm-plus); border-radius: var(--radius-xs); background: linear-gradient(90deg, var(--bg-elevated) 25%, var(--overlay-shimmer-hi) 50%, var(--bg-elevated) 75%); background-size: 200% 100%; animation: shimmer var(--anim-shimmer) infinite; margin-bottom: var(--space-xxs); }

/* Streamlit button overrides for action buttons inside bubbles.
   Keep them small, inline, and never full-width. */
div[class*="st-key-edit-"] button,
div[class*="st-key-regen-msg-"] button,
div[class*="st-key-copy-"] button,
div[class*="st-key-listen-"] button { background: var(--overlay-ghost) !important; border: var(--line) solid var(--border-default) !important; border-radius: var(--radius-sm) !important; color: var(--text-muted) !important; padding: var(--space-xxxs) var(--space-sm-plus) !important; font-size: var(--font-tiny) !important; min-height: 0 !important; height: auto !important; width: auto !important; display: inline-flex !important; }
div[class*="st-key-edit-"] button:hover,
div[class*="st-key-regen-msg-"] button:hover,
div[class*="st-key-copy-"] button:hover,
div[class*="st-key-listen-"] button:hover { background: var(--overlay-ghost-hover) !important; color: var(--text-secondary) !important; }
div[class*="st-key-copy-"], div[class*="st-key-listen-"] { display: inline-flex; }
/* Edit + meta share one row: keep Edit right-aligned and compact */
div[class*="st-key-edit-"] { display: flex; justify-content: flex-end; }
'''
