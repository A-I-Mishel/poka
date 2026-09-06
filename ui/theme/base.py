"""Base theme layer — font import, tokens as CSS vars, global resets."""

BASE_CSS: str = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
    --bg-base: #09090b;
    --bg-elevated: #12121a;
    --bg-surface: #1a1a24;
    --bg-overlay: rgba(18,18,26,0.92);
    --bg-code: #0d0d12;
    --accent-primary: #a78bfa;
    --accent-primary-hover: #c4b5fd;
    --accent-primary-glow: rgba(167,139,250,0.25);
    --accent-primary-deep: #7c3aed;
    --accent-secondary: #38bdf8;
    --accent-secondary-deep: #0ea5e9;
    --accent-success: #34d399;
    --accent-success-glow: rgba(52,211,153,0.5);
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
    --space-xxxs: 2px;
    --space-xs: 4px;
    --space-xxs: 6px;
    --space-sm: 8px;
    --space-sm-plus: 10px;
    --space-md: 12px;
    --space-md-plus: 14px;
    --space-lg: 16px;
    --space-lg-plus: 18px;
    --space-xl: 24px;
    --space-xl-minus: 20px;
    --space-xl-plus: 30px;
    --space-xxl: 32px;
    --space-xxxl: 48px;
    --overlay-ghost: rgba(255,255,255,0.04);
    --overlay-ghost-hover: rgba(255,255,255,0.08);
    --overlay-ghost-faint: rgba(255,255,255,0.02);
    --overlay-line-ghost: rgba(255,255,255,0.06);
    --overlay-shimmer-hi: rgba(255,255,255,0.03);
    --bubble-user-from: rgba(167,139,250,0.15);
    --bubble-user-to: rgba(124,58,237,0.1);
    --mark-hit: rgba(167,139,250,0.35);
    --radius-xs: 4px;
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
    --shadow-avatar-bot: 0 2px 8px rgba(167,139,250,0.3);
    --shadow-avatar-user: 0 2px 8px rgba(56,189,248,0.3);
    --shadow-bubble-user: 0 2px 8px rgba(167,139,250,0.08);
    --shadow-dock: 0 8px 32px rgba(0,0,0,0.5), 0 0 0 1px rgba(167,139,250,0.08);
    --shadow-dock-focus: 0 8px 32px rgba(0,0,0,0.5), 0 0 20px rgba(167,139,250,0.12);
    --font-stack: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif;
    --font-mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    --font-tiny: 11px;
    --font-code: 13px;
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
    --leading-compact: 1.2;
    --leading-card: 1.3;
    --leading-tight: 1.35;
    --leading-normal: 1.65;
    --leading-relaxed: 1.7;
    --tracking-tight: -0.02em;
    --tracking-snug: -0.01em;
    --tracking-wide: 0.05em;
    --tracking-wider: 0.06em;
    --tracking-widest: 0.08em;
    --opacity-disabled: 0.55;
    --anim-fast: 150ms;
    --anim-normal: 250ms;
    --anim-slow: 400ms;
    --anim-thinking: 1.4s;
    --anim-shimmer: 1.5s;
    --anim-easing: cubic-bezier(0.2, 0, 0, 1);
    --anim-spring: cubic-bezier(0.34, 1.56, 0.64, 1);
    --line: 1px;
    --hero-h-min: 26px;
    --hero-h-max: 34px;
    --sidebar-width: 280px;
    --sidebar-width-md: 240px;
    --composer-bottom: 24px;
    --chat-bottom-pad: 150px;
    --avatar-size: 28px;
    --brand-mark-size: 28px;
    --hero-mark-size: 40px;
    --assistant-mark-size: 18px;
    --artifact-icon-size: 30px;
    --chat-max-width: 680px;
    --bubble-max-width: 600px;
    --composer-max-width: 640px;
    --content-max-width: 900px;
    --home-max-width: 660px;
    --chip-name-max: 220px;
    --chip-name-max-mobile: 140px;
    --composer-btn-size: 34px;
    --composer-control-size: 40px;
    --btn-min-height: 36px;
    --think-lift: 3px;
    --z-composer: 9999;
    --z-sidebar-mobile: 60;
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

.main .block-container { max-width: var(--content-max-width) !important; margin: 0 auto !important; }
section[data-testid="stMain"] .block-container { max-width: var(--content-max-width) !important; margin: 0 auto !important; padding-bottom: var(--chat-bottom-pad) !important; }
section[data-testid="stMain"] { background: var(--bg-base); color: var(--text-primary); }

@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { animation-duration: 0.01ms; animation-iteration-count: 1; transition-duration: 0.01ms; }
}
"""
