"""Streamlit native overrides — data-testid selectors only, !important allowed."""

STREAMLIT_CSS: str = """
div[data-testid="stAppViewContainer"] { background: var(--bg-base) !important; color: var(--text-primary) !important; }

section[data-testid="stSidebar"] { background: var(--bg-elevated) !important; border-right: 1px solid var(--border-subtle) !important; }

.stButton > button { background: var(--bg-surface) !important; border: 1px solid var(--border-default) !important; border-radius: var(--radius-md) !important; color: var(--text-primary) !important; }

.stButton > button:hover { border-color: var(--border-hover) !important; }

div[data-testid="stBaseButton-primary"] > button { background: linear-gradient(135deg, var(--accent-primary), var(--accent-primary-hover)) !important; border: 1px solid var(--border-accent) !important; color: var(--text-primary) !important; box-shadow: var(--shadow-glow) !important; }

div[data-testid="stTextInput"] input { background: var(--bg-surface) !important; border: 1px solid var(--border-default) !important; border-radius: var(--radius-md) !important; color: var(--text-primary) !important; }

div[data-testid="stTextInput"] input:focus { border-color: var(--border-accent) !important; box-shadow: var(--shadow-glow) !important; outline: none !important; }

div[data-testid="stTextArea"] textarea { background: var(--bg-surface) !important; border: 1px solid var(--border-default) !important; border-radius: var(--radius-md) !important; color: var(--text-primary) !important; }

div[data-testid="stTextArea"] textarea:focus { border-color: var(--border-accent) !important; box-shadow: var(--shadow-glow) !important; outline: none !important; }

div[data-testid="stSelectbox"] div[data-baseweb="select"] { background: var(--bg-surface) !important; border: 1px solid var(--border-default) !important; border-radius: var(--radius-md) !important; color: var(--text-primary) !important; }

.streamlit-expanderHeader { background: var(--bg-elevated) !important; border: 1px solid var(--border-subtle) !important; border-radius: var(--radius-md) !important; color: var(--text-primary) !important; }

.streamlit-expanderContent { background: var(--bg-elevated) !important; border: 1px solid var(--border-subtle) !important; color: var(--text-secondary) !important; }

div[data-testid="stTabs"] div[role="tablist"] { border-bottom: 1px solid var(--border-subtle) !important; }

div[data-testid="stTabs"] button[role="tab"] { color: var(--text-muted) !important; }

div[data-testid="stTabs"] button[role="tab"][aria-selected="true"] { color: var(--accent-primary-hover) !important; border-bottom: 2px solid var(--accent-primary) !important; }

div[data-testid="stFileUploader"] { background: var(--bg-elevated) !important; border: 1px dashed var(--border-default) !important; border-radius: var(--radius-lg) !important; }

div[data-testid="stFileUploader"]:hover { border-color: var(--border-accent) !important; box-shadow: var(--shadow-glow) !important; }

div[data-testid="stDataFrame"] { background: var(--bg-elevated) !important; border: 1px solid var(--border-subtle) !important; border-radius: var(--radius-md) !important; }

div[data-testid="stToast"] { background: var(--bg-overlay) !important; backdrop-filter: blur(var(--composer-blur)) !important; border: 1px solid var(--border-default) !important; border-radius: var(--radius-md) !important; color: var(--text-primary) !important; }

div[data-testid="stSpinner"] { color: var(--accent-primary) !important; }

div[data-testid="stProgress"] div[role="progressbar"] { background: linear-gradient(90deg, var(--accent-primary), var(--accent-secondary)) !important; }
"""
