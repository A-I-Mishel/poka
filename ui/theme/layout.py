"""Layout theme layer — app shell, sidebar, main, chat, composer dock."""

LAYOUT_CSS: str = """
.app-shell { display: flex; min-height: 100vh; background: var(--bg-base); color: var(--text-primary); }

.sidebar { width: var(--sidebar-width); background: var(--bg-elevated); border-right: var(--border-subtle); display: flex; flex-direction: column; }

.sidebar-header { padding: var(--space-lg) var(--space-lg) var(--space-md); border-bottom: var(--border-subtle); }

.sidebar-section { padding: var(--space-md) var(--space-lg); }

.sidebar-section-title { color: var(--text-muted); font-size: var(--font-xs); font-weight: var(--weight-semibold); text-transform: uppercase; letter-spacing: 0.06em; margin: var(--space-md) 0 var(--space-sm); }

.main-content { flex: 1 1 auto; min-width: 0; background: var(--bg-base); }

.chat-area { max-width: 100%; padding: var(--space-lg) var(--space-xl) var(--chat-bottom-pad); }

/* Composer dock: the keyed Streamlit container (.st-key-composer-dock)
   is the real wrapper; .composer-dock kept as an alias selector. */
.composer-dock,
.st-key-composer-dock {
    position: fixed;
    bottom: var(--space-lg);
    left: calc(50% + var(--sidebar-width) / 2);
    transform: translateX(-50%);
    width: min(var(--composer-max-width), calc(100% - var(--space-xxl) - var(--sidebar-width)));
    background: var(--bg-overlay);
    backdrop-filter: blur(var(--composer-blur));
    -webkit-backdrop-filter: blur(var(--composer-blur));
    border: var(--line) solid var(--border-hover);
    border-radius: var(--radius-full);
    padding: var(--space-sm-plus) var(--space-md-plus);
    z-index: var(--z-composer);
    box-shadow: var(--shadow-dock);
}

.composer-dock:focus-within,
.st-key-composer-dock:focus-within {
    border-color: var(--border-accent);
    box-shadow: var(--shadow-dock-focus);
}

.composer-chips,
.st-key-composer-chips { display: flex; flex-wrap: wrap; gap: var(--space-sm); margin-bottom: var(--space-sm); padding: 0 var(--space-xs); }
.st-key-composer-chips:empty { display: none; }
"""
