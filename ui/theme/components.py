"""Components theme layer — glass, buttons, badges, inputs, project cards."""

COMPONENTS_CSS: str = """
.glass { background: var(--bg-overlay); backdrop-filter: blur(var(--composer-blur)); border: var(--border-default); border-radius: var(--radius-lg); box-shadow: var(--shadow-md); }

.btn { display: inline-flex; align-items: center; gap: var(--space-sm); border-radius: var(--radius-md); padding: var(--space-sm) var(--space-lg); font-size: var(--font-sm); font-weight: var(--weight-semibold); color: var(--text-primary); background: var(--bg-surface); border: var(--border-default); transition: background var(--anim-fast) var(--anim-easing), border-color var(--anim-fast) var(--anim-easing); }

.btn:hover { border-color: var(--border-hover); }

.btn-primary { background: linear-gradient(135deg, var(--accent-primary), var(--accent-primary-hover)); border-color: var(--border-accent); color: var(--text-primary); box-shadow: var(--shadow-glow); padding: 6px 12px; font-size: 12px; }

.btn-primary:hover { border-color: var(--accent-primary-hover); }

.btn-ghost { background: transparent; border-color: transparent; color: var(--text-secondary); }

.btn-ghost:hover { background: var(--bg-surface); color: var(--text-primary); }

.badge { display: inline-flex; align-items: center; border-radius: var(--radius-full); padding: var(--space-xs) var(--space-md); font-size: var(--font-xs); font-weight: var(--weight-medium); background: var(--bg-surface); border: var(--border-default); color: var(--text-secondary); }

.badge-accent { background: var(--accent-primary-glow); border-color: var(--border-accent); color: var(--accent-primary-hover); }

.input-modern { background: var(--bg-surface); border: var(--border-default); border-radius: var(--radius-md); color: var(--text-primary); padding: var(--space-sm) var(--space-md); font-size: var(--font-sm); }

.input-modern:focus { border-color: var(--border-accent); box-shadow: var(--shadow-glow); outline: none; }

.project-card { display: flex; align-items: center; gap: var(--space-md); background: transparent; border: var(--border-subtle); border-radius: var(--radius-md); padding: 8px 10px; }

.project-card:hover { background: var(--bg-surface); border-color: var(--border-default); }

.project-card.active { background: var(--bg-surface); border-color: var(--border-accent); box-shadow: inset 3px 0 0 var(--accent-primary); }

.project-card-icon { width: var(--space-xl); height: var(--space-xl); border-radius: var(--radius-md); display: inline-flex; align-items: center; justify-content: center; background: linear-gradient(135deg, var(--accent-primary), var(--accent-secondary)); color: var(--text-primary); }
"""
