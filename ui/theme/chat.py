"""Chat theme layer — messages, avatars, bubbles, code, thinking, skeleton."""

CHAT_CSS: str = """
.msg-row { display: flex; gap: 12px; padding: 8px 0; max-width: 680px; }

.msg-row-user { display: flex; gap: 12px; padding: 8px 0; max-width: 680px; flex-direction: row-reverse; }

.msg-avatar { width: 28px; height: 28px; font-size: 11px; border-radius: var(--radius-full); display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; }

.msg-avatar-bot { width: 28px; height: 28px; font-size: 11px; border-radius: var(--radius-full); background: linear-gradient(135deg, var(--accent-primary), var(--accent-secondary)); color: var(--text-primary); display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; }

.msg-avatar-user { width: 28px; height: 28px; font-size: 11px; border-radius: var(--radius-full); background: linear-gradient(135deg, var(--accent-secondary), var(--accent-success)); color: var(--text-inverse); display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; }

div[data-testid="stChatMessageAvatarAssistant"], div[data-testid="stChatMessageAvatarUser"] { display: none; }

.msg-status { width: var(--space-sm); height: var(--space-sm); border-radius: var(--radius-full); background: var(--accent-success); display: inline-block; }

.msg-bubble-assistant { background: var(--bg-elevated); border: var(--border-subtle); border-radius: var(--radius-lg); padding: 12px 16px; color: var(--text-primary); font-size: var(--font-md); line-height: 1.5; }

.msg-bubble-user { background: var(--bg-surface); border: var(--border-default); border-radius: var(--radius-lg); padding: 10px 14px; max-width: fit-content; margin-left: auto; color: var(--text-primary); font-size: var(--font-md); line-height: 1.5; }

.msg-actions { display: flex; gap: 8px; margin-top: 6px; opacity: 0; transition: opacity var(--anim-fast) var(--anim-easing); }

.msg-row:hover .msg-actions { opacity: 1; }

.msg-row-user:hover .msg-actions { opacity: 1; }

.msg-action-btn { background: rgba(255,255,255,0.04); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); color: var(--text-muted); padding: 6px 10px; font-size: 11px; }

.msg-action-btn:hover { background: rgba(255,255,255,0.08); color: var(--text-primary); border-color: var(--border-hover); }

.poka-copy { background: rgba(255,255,255,0.04); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); color: var(--text-muted); padding: 6px 10px; font-size: 11px; cursor: pointer; }

.poka-copy:hover { background: rgba(255,255,255,0.08); color: var(--text-primary); }

.poka-code-copy { background: rgba(255,255,255,0.04); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); color: var(--text-muted); padding: 6px 10px; font-size: 11px; cursor: pointer; }

.poka-code-copy:hover { background: rgba(255,255,255,0.08); color: var(--text-primary); }

div[class*="st-key-edit-"] button, div[class*="st-key-regen-msg-"] button { background: rgba(255,255,255,0.04) !important; border: 1px solid var(--border-subtle) !important; border-radius: var(--radius-sm) !important; color: var(--text-muted) !important; padding: 6px 10px !important; font-size: 11px !important; min-height: 0 !important; width: auto !important; }

div[class*="st-key-edit-"] button:hover, div[class*="st-key-regen-msg-"] button:hover { background: rgba(255,255,255,0.08) !important; color: var(--text-primary) !important; }

.code-block { background: var(--bg-elevated); border: var(--border-default); border-radius: var(--radius-md); overflow: hidden; margin: 8px 0; }

.code-header { display: flex; align-items: center; gap: var(--space-sm); padding: 6px 10px; border-bottom: var(--border-subtle); }

.code-dot-red { width: var(--space-md); height: var(--space-md); border-radius: var(--radius-full); background: var(--accent-error); }

.code-dot-yellow { width: var(--space-md); height: var(--space-md); border-radius: var(--radius-full); background: var(--accent-warning); }

.code-dot-green { width: var(--space-md); height: var(--space-md); border-radius: var(--radius-full); background: var(--accent-success); }

.code-lang { margin-left: auto; color: var(--text-muted); font-size: var(--font-xs); font-family: var(--font-mono); }

.code-body { padding: var(--space-lg); font-family: var(--font-mono); font-size: var(--font-sm); color: var(--text-primary); overflow-x: auto; }

.thinking-dots { display: inline-flex; gap: var(--space-xs); align-items: center; padding: 12px 16px; }

.thinking-dots span { width: var(--space-sm); height: var(--space-sm); border-radius: var(--radius-full); background: var(--text-muted); animation: thinkingBounce var(--anim-slow) infinite var(--anim-easing); }

.thinking-dots span:nth-child(2) { animation-delay: 150ms; }

.thinking-dots span:nth-child(3) { animation-delay: 300ms; }

.skeleton-msg { background: var(--bg-elevated); border: var(--border-subtle); border-radius: var(--radius-lg); padding: var(--space-lg); }

.skeleton-avatar { width: 28px; height: 28px; border-radius: var(--radius-full); background: var(--bg-surface); animation: shimmer var(--anim-slow) infinite var(--anim-easing); }

.skeleton-line { height: var(--space-md); border-radius: var(--radius-sm); background: var(--bg-surface); margin: var(--space-sm) 0; animation: shimmer var(--anim-slow) infinite var(--anim-easing); }
"""
