"""Base theme layer — font import, tokens as CSS vars, global resets."""

BASE_CSS: str = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
    --bg-base: #09090b;
    --bg-elevated: #12121a;
    --bg-surface: #1a1a24;
    --bg-overlay: rgba(18,18,26,0.92);
    --accent-primary: #a78bfa;
    --accent-primary-hover: #c4b5fd;
    --accent-primary-glow: rgba(167,139,250,0.25);
    --accent-secondary: #38bdf8;
    --accent-success: #34d399;
    --accent-warning: #fbbf24;
    --accent-error: #f87171;
    --text-primary: #f8fafc;
    --text-secondary: #94a3b8;
    --text-muted: #64748b;
    --text-inverse: #0f172a;
    --border-subtle: rgba(255,255,255,0.05);
    --border-default: rgba(255,255,255,0.08);
    --border-hover: rgba(255,255,255,0.15);
    --border-accent: rgba(167,139,250,0.25);
    --space-xs: 4px;
    --space-sm: 8px;
    --space-md: 12px;
    --space-lg: 16px;
    --space-xl: 24px;
    --space-xxl: 32px;
    --space-xxxl: 48px;
    --radius-sm: 6px;
    --radius-md: 10px;
    --radius-lg: 14px;
    --radius-xl: 20px;
    --radius-full: 9999px;
    --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.4);
    --shadow-md: 0 4px 16px rgba(0, 0, 0, 0.45);
    --shadow-lg: 0 16px 44px rgba(0, 0, 0, 0.55);
    --shadow-glow: 0 0 24px rgba(167, 139, 250, 0.22);
    --shadow-glow-strong: 0 0 32px rgba(167, 139, 250, 0.38);
    --font-stack: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif;
    --font-mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    --font-xs: 12px;
    --font-sm: 14px;
    --font-md: 15px;
    --font-lg: 16px;
    --font-xl: 18px;
    --font-xxl: 24px;
    --font-xxxl: 32px;
    --weight-regular: 400;
    --weight-medium: 500;
    --weight-semibold: 600;
    --weight-bold: 700;
    --leading-tight: 1.35;
    --leading-normal: 1.65;
    --leading-relaxed: 1.7;
    --anim-fast: 150ms;
    --anim-normal: 250ms;
    --anim-slow: 400ms;
    --anim-easing: cubic-bezier(0.2, 0, 0, 1);
    --anim-spring: cubic-bezier(0.34, 1.56, 0.64, 1);
    --sidebar-width: 280px;
    --sidebar-width-md: 240px;
    --composer-bottom: 24px;
    --chat-bottom-pad: 120px;
    --scroll-size: 6px;
    --focus-width: 2px;
    --composer-blur: 24px;
}

* { font-family: var(--font-stack); }

#MainMenu { display: none; }
footer { display: none; }
header[data-testid="stHeader"] { display: none; }
div[data-testid="stToolbar"] { display: none; }

::-webkit-scrollbar { width: var(--scroll-size); height: var(--scroll-size); }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border-default); border-radius: var(--radius-full); }
::-webkit-scrollbar-thumb:hover { background: var(--border-hover); }

::selection { background: var(--accent-primary-glow); color: var(--text-primary); }

:focus-visible { outline: var(--focus-width) solid var(--accent-primary); outline-offset: var(--space-xs); }

.main .block-container { max-width: 900px !important; margin: 0 auto !important; }

@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { animation-duration: 0.01ms; animation-iteration-count: 1; transition-duration: 0.01ms; }
}
"""
