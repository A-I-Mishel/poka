"""Streamlit native overrides — data-testid selectors only, !important allowed."""

STREAMLIT_CSS: str = """
div[data-testid="stAppViewContainer"] { background: var(--bg-base) !important; color: var(--text-primary) !important; }

section[data-testid="stSidebar"] { background: var(--bg-elevated) !important; border-right: var(--line) solid var(--border-subtle) !important; }

.stButton > button { background: var(--bg-surface) !important; border: var(--line) solid var(--border-default) !important; border-radius: var(--radius-md) !important; color: var(--text-primary) !important; }

.stButton > button:hover { border-color: var(--border-hover) !important; }

/* Testid-addressed twin: tooltip-wrapped buttons carry no .stButton ancestor
   hook, so they would otherwise keep Streamlit's default face. */
button[data-testid="stBaseButton-secondary"] { background: var(--bg-surface) !important; border: var(--line) solid var(--border-default) !important; border-radius: var(--radius-md) !important; color: var(--text-primary) !important; }

button[data-testid="stBaseButton-secondary"]:hover { border-color: var(--border-hover) !important; }

button[data-testid="stBaseButton-primary"] { background: linear-gradient(135deg, var(--accent-primary), var(--accent-primary-deep)) !important; border: none !important; color: var(--text-primary) !important; border-radius: var(--radius-md) !important; font-weight: var(--weight-semibold) !important; box-shadow: var(--shadow-avatar-bot) !important; }

div[data-testid="stTextInput"] input { background: var(--bg-surface) !important; border: var(--line) solid var(--border-default) !important; border-radius: var(--radius-md) !important; color: var(--text-primary) !important; }

div[data-testid="stTextInput"] input:focus { border-color: var(--border-accent) !important; box-shadow: var(--shadow-glow) !important; outline: none !important; }

div[data-testid="stTextArea"] textarea { background: var(--bg-surface) !important; border: var(--line) solid var(--border-default) !important; border-radius: var(--radius-md) !important; color: var(--text-primary) !important; }

div[data-testid="stTextArea"] textarea:focus { border-color: var(--border-accent) !important; box-shadow: var(--shadow-glow) !important; outline: none !important; }

div[data-testid="stSelectbox"] div[data-baseweb="select"] { background: var(--bg-surface) !important; border: var(--line) solid var(--border-default) !important; border-radius: var(--radius-md) !important; color: var(--text-primary) !important; }

.streamlit-expanderHeader { background: var(--bg-elevated) !important; border: var(--line) solid var(--border-subtle) !important; border-radius: var(--radius-md) !important; color: var(--text-primary) !important; }

.streamlit-expanderContent { background: var(--bg-elevated) !important; border: var(--line) solid var(--border-subtle) !important; color: var(--text-secondary) !important; }

div[data-testid="stTabs"] div[role="tablist"] { border-bottom: var(--line) solid var(--border-subtle) !important; }

div[data-testid="stTabs"] button[role="tab"] { color: var(--text-muted) !important; }

div[data-testid="stTabs"] button[role="tab"][aria-selected="true"] { color: var(--accent-primary-hover) !important; border-bottom: calc(var(--line) * 2) solid var(--accent-primary) !important; }

div[data-testid="stFileUploader"] { background: var(--bg-elevated) !important; border: var(--line) dashed var(--border-default) !important; border-radius: var(--radius-lg) !important; }

div[data-testid="stFileUploader"]:hover { border-color: var(--border-accent) !important; box-shadow: var(--shadow-glow) !important; }

div[data-testid="stDataFrame"] { background: var(--bg-elevated) !important; border: var(--line) solid var(--border-subtle) !important; border-radius: var(--radius-md) !important; }

div[data-testid="stToast"] { background: var(--bg-overlay) !important; backdrop-filter: blur(var(--composer-blur)) !important; border: var(--line) solid var(--border-default) !important; border-radius: var(--radius-md) !important; color: var(--text-primary) !important; }

div[data-testid="stSpinner"] { color: var(--accent-primary) !important; }

div[data-testid="stProgress"] div[role="progressbar"] { background: linear-gradient(90deg, var(--accent-primary), var(--accent-secondary)) !important; }
"""
