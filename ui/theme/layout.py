"""Layout theme layer — app shell, sidebar, main, chat, composer dock."""

LAYOUT_CSS: str = """
.app-shell { display: flex; min-height: 100vh; background: var(--bg-base); color: var(--text-primary); }

.sidebar { width: var(--sidebar-width); background: var(--bg-elevated); border-right: var(--border-subtle); display: flex; flex-direction: column; }

.sidebar-header { padding: var(--space-lg) var(--space-lg) var(--space-md); border-bottom: var(--border-subtle); }

.sidebar-section { padding: var(--space-md) var(--space-lg); }

.sidebar-section-title { color: var(--text-muted); font-size: var(--font-xs); font-weight: var(--weight-semibold); text-transform: uppercase; letter-spacing: 0.06em; margin: var(--space-md) 0 var(--space-sm); }

.main-content { flex: 1 1 auto; min-width: 0; background: var(--bg-base); }

.chat-area { max-width: 100%; padding: 16px 20px 140px; }

.composer-dock { position: fixed; bottom: 16px; left: 50%; transform: translateX(-50%); width: min(640px, calc(100% - 40px)); background: var(--bg-overlay); backdrop-filter: blur(var(--composer-blur)); border: var(--border-default); border-radius: var(--radius-xl); box-shadow: var(--shadow-lg); padding: 10px 14px; z-index: 50; }

.composer-dock:focus-within { border-color: var(--border-accent); box-shadow: var(--shadow-lg), var(--shadow-glow); }
"""
