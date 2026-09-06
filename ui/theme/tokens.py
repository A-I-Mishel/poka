"""Central design tokens — single source of truth for theme values.

Visual-only layer. No Streamlit calls, no side effects. Python layout
constants (image preview width, text-area height) live in
services/limits.py so behavior stays auditable; CSS strings live here.
"""

TOKENS: dict = {
    "color": {
        "bg": {
            "base": "#09090b",
            "elevated": "#12121a",
            "surface": "#1a1a24",
            "overlay": "rgba(18,18,26,0.92)",
        },
        "accent": {
            "primary": "#a78bfa",
            "primaryHover": "#c4b5fd",
            "primaryGlow": "rgba(167,139,250,0.25)",
            "secondary": "#38bdf8",
            "success": "#34d399",
            "warning": "#fbbf24",
            "error": "#f87171",
        },
        "text": {
            "primary": "#f8fafc",
            "secondary": "#94a3b8",
            "muted": "#64748b",
            "inverse": "#0f172a",
        },
        "border": {
            "subtle": "rgba(255,255,255,0.05)",
            "default": "rgba(255,255,255,0.08)",
            "hover": "rgba(255,255,255,0.15)",
            "accent": "rgba(167,139,250,0.25)",
        },
    },
    "space": {
        "xs": "4px",
        "sm": "8px",
        "md": "12px",
        "lg": "16px",
        "xl": "24px",
        "xxl": "32px",
        "xxxl": "48px",
    },
    "radius": {
        "sm": "6px",
        "md": "10px",
        "lg": "14px",
        "xl": "20px",
        "full": "9999px",
    },
    "shadow": {
        "sm": "0 1px 2px rgba(0, 0, 0, 0.4)",
        "md": "0 4px 16px rgba(0, 0, 0, 0.45)",
        "lg": "0 16px 44px rgba(0, 0, 0, 0.55)",
        "glow": "0 0 24px rgba(167, 139, 250, 0.22)",
        "glowStrong": "0 0 32px rgba(167, 139, 250, 0.38)",
    },
    "typography": {
        "fontStack": "'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif",
        "monoStack": "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
        "sizes": {
            "xs": "12px",
            "sm": "14px",
            "md": "15px",
            "lg": "16px",
            "xl": "18px",
            "xxl": "24px",
            "xxxl": "32px",
        },
        "weights": {
            "regular": 400,
            "medium": 500,
            "semibold": 600,
            "bold": 700,
        },
        "lineHeights": {
            "tight": 1.35,
            "normal": 1.65,
            "relaxed": 1.7,
        },
    },
    "animation": {
        "fast": "150ms",
        "normal": "250ms",
        "slow": "400ms",
        "easing": "cubic-bezier(0.2, 0, 0, 1)",
        "spring": "cubic-bezier(0.34, 1.56, 0.64, 1)",
    },
}

__all__ = ["TOKENS"]
