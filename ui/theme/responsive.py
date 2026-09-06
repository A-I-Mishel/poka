"""Responsive theme layer — breakpoints for sidebar and composer."""

RESPONSIVE_CSS: str = """
@media (max-width: 1024px) {
    .sidebar { width: var(--sidebar-width-md); }
    .chat-area { padding: var(--space-lg) var(--space-md) var(--chat-bottom-pad); }
}

@media (max-width: 768px) {
    .sidebar { position: fixed; left: 0; top: 0; bottom: 0; transform: translateX(-100%); transition: transform var(--anim-normal) var(--anim-easing); z-index: var(--z-sidebar-mobile); }
    .sidebar.open { transform: translateX(0); }
    .chat-area { padding: var(--space-md) var(--space-md) var(--chat-bottom-pad); }
    .composer-dock, .st-key-composer-dock { width: calc(100% - var(--space-xl)); bottom: var(--space-md); left: 50%; border-radius: var(--radius-full); }
}
"""
