"""Animations theme layer — keyframes plus utility classes."""

ANIMATIONS_CSS: str = """
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }

@keyframes slideUp { from { opacity: 0; transform: translateY(var(--space-sm)); } to { opacity: 1; transform: translateY(0); } }

@keyframes scaleIn { from { opacity: 0; transform: scale(0.97); } to { opacity: 1; transform: scale(1); } }

@keyframes pulseGlow { 0%, 100% { box-shadow: var(--shadow-glow); } 50% { box-shadow: var(--shadow-glow-strong); } }

@keyframes spin { to { transform: rotate(360deg); } }

@keyframes toastSlideIn { from { opacity: 0; transform: translateY(var(--space-sm)); } to { opacity: 1; transform: translateY(0); } }

@keyframes thinkingBounce { 0%, 100% { opacity: 0.3; transform: translateY(0); } 50% { opacity: 1; transform: translateY(calc(var(--think-lift) * -1)); } }

@keyframes shimmer { 0% { opacity: 0.5; } 50% { opacity: 1; } 100% { opacity: 0.5; } }

.animate-fadeIn { animation: fadeIn var(--anim-normal) var(--anim-easing) both; }

.animate-slideUp { animation: slideUp var(--anim-normal) var(--anim-easing) both; }

.animate-scaleIn { animation: scaleIn var(--anim-fast) var(--anim-spring) both; }

.animate-pulseGlow { animation: pulseGlow var(--anim-slow) infinite var(--anim-easing); }
"""
