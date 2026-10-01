"""Design tokens, None-safe formatters and shared CSS for the light fintech UI."""
from __future__ import annotations

from typing import Any, Optional

import streamlit as st

# ---- tokens ---------------------------------------------------------------
BG, CARD, BORDER = "#f8fafc", "#ffffff", "#e2e8f0"
INK, MUTED, FAINT = "#0f172a", "#64748b", "#94a3b8"
UP, DOWN, ACCENT, WARN = "#16a34a", "#dc2626", "#2563eb", "#d97706"
UP_BG, DOWN_BG, WARN_BG, ACCENT_BG = "#dcfce7", "#fee2e2", "#fef3c7", "#dbeafe"
VERDICT = {"Invest": (UP, UP_BG), "Watch": (WARN, WARN_BG), "Avoid": (DOWN, DOWN_BG)}
FONT = "Inter, -apple-system, Segoe UI, Roboto, sans-serif"


# ---- formatters (never raise, never print 'None') --------------------------
def _ok(x: Any) -> bool:
    return isinstance(x, (int, float)) and x == x and x not in (float("inf"), float("-inf"))


def num(x: Any, d: int = 2, prefix: str = "", suffix: str = "", na: str = "–") -> str:
    return f"{prefix}{x:,.{d}f}{suffix}" if _ok(x) else na


def pct(x: Any, d: int = 1, sign: bool = False, na: str = "–") -> str:
    if not _ok(x):
        return na
    return f"{x:+,.{d}f}%" if sign else f"{x:,.{d}f}%"


def inr(x: Any, d: int = 2, na: str = "–") -> str:
    return num(x, d, prefix="₹", na=na)


def cr(x: Any, na: str = "–") -> str:
    """Rs crore, using lakh-crore for large values."""
    if not _ok(x):
        return na
    if abs(x) >= 1e5:
        return f"₹{x / 1e5:,.2f} L cr"
    return f"₹{x:,.0f} cr"


def tone(x: Any, good_when_positive: bool = True) -> str:
    if not _ok(x) or x == 0:
        return MUTED
    return UP if (x > 0) == good_when_positive else DOWN


# ---- html helpers ----------------------------------------------------------
def pill(text: str, fg: str, bg: str) -> str:
    return (f"<span style='display:inline-block;padding:2px 10px;border-radius:999px;"
            f"font-weight:600;font-size:.78rem;color:{fg};background:{bg}'>{text}</span>")


def kpi(label: str, value: str, sub: str = "", color: str = INK) -> str:
    return (f"<div class='kpi'><div class='kpi-l'>{label}</div>"
            f"<div class='kpi-v' style='color:{color}'>{value}</div>"
            f"<div class='kpi-s'>{sub}</div></div>")


def style(fig, height: int = 320, legend: bool = True):
    """Shared Plotly look: light grid, Inter font, transparent paper, compact margins."""
    fig.update_layout(
        height=height, margin=dict(l=8, r=8, t=24, b=8), paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)", font=dict(family=FONT, size=12, color=INK),
        hoverlabel=dict(bgcolor="#ffffff", bordercolor=BORDER, font_size=12),
        showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0, font_size=11),
    )
    fig.update_xaxes(showgrid=False, linecolor=BORDER, tickfont=dict(color=MUTED))
    fig.update_yaxes(gridcolor="#eef2f7", zeroline=False, tickfont=dict(color=MUTED))
    return fig


CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"], .stApp {{ font-family: {FONT}; }}
.stApp {{ background: {BG}; color: {INK}; }}
header[data-testid="stHeader"] {{ background: transparent; }}
.block-container {{ max-width: 1280px; padding: 1.2rem 1.4rem 3rem; }}
div[data-testid="stVerticalBlockBorderWrapper"] {{ background: {CARD}; border-radius: 14px;
    border-color: {BORDER}; box-shadow: 0 1px 2px rgba(15,23,42,.04); }}
.hero-price {{ font-size: clamp(1.9rem, 4vw, 2.7rem); font-weight: 800; letter-spacing: -.02em; line-height: 1.05; }}
.hero-name {{ font-size: clamp(1.05rem, 2vw, 1.3rem); font-weight: 700; }}
.muted {{ color: {MUTED}; font-size: .82rem; }}
.kpi {{ padding: 4px 2px; }}
.kpi-l {{ color: {MUTED}; font-size: .74rem; font-weight: 500; text-transform: uppercase; letter-spacing: .04em; }}
.kpi-v {{ font-size: 1.2rem; font-weight: 700; line-height: 1.25; overflow-wrap: anywhere; }}
.kpi-s {{ color: {FAINT}; font-size: .74rem; }}
.verdict-word {{ font-size: 1.9rem; font-weight: 800; letter-spacing: -.02em; line-height: 1.1; }}
.range-bar {{ position: relative; height: 6px; border-radius: 4px; background: {BORDER}; margin: 10px 0 4px; }}
.range-dot {{ position: absolute; top: -5px; width: 16px; height: 16px; border-radius: 50%;
    background: {ACCENT}; border: 3px solid #fff; box-shadow: 0 1px 3px rgba(0,0,0,.25); }}
.insight {{ display: flex; gap: 8px; align-items: flex-start; padding: 6px 0; border-bottom: 1px solid #f1f5f9; font-size: .9rem; }}
.insight:last-child {{ border-bottom: 0; }}
.dot {{ flex: 0 0 8px; height: 8px; border-radius: 50%; margin-top: 7px; }}
.stTabs [data-baseweb="tab-list"] {{ gap: 4px; }}
.stTabs [data-baseweb="tab"] {{ font-weight: 600; }}
div[data-testid="stMetric"] {{ overflow-wrap: anywhere; }}
.disclaimer {{ color: {FAINT}; font-size: .74rem; text-align: center; padding-top: 1.5rem; }}
.logo {{ display: inline-flex; align-items: center; gap: 6px; padding-top: 2px; }}
.logo-mark {{ position: relative; display: inline-block; width: 1.55rem; height: 1.7rem; }}
.logo-mark span {{ position: absolute; top: -.1rem; font-size: 1.9rem; font-weight: 800; line-height: 1.7rem; }}
.lm-a {{ left: 0; color: #2563eb; }}
.lm-b {{ left: .5rem; top: .05rem; color: #16a34a; opacity: .92; }}
.logo-name {{ font-weight: 800; font-size: 1.2rem; letter-spacing: -.01em; }}
@keyframes slideDown {{ from {{ opacity: 0; transform: translateY(-14px); }} to {{ opacity: 1; transform: none; }} }}
.st-key-panel {{ animation: slideDown .32s ease-out; }}
.st-key-nav [data-baseweb="button-group"], .st-key-nav div[role="radiogroup"] {{ width: 100%; }}
.plain-table {{ width: 100%; border-collapse: collapse; font-size: .85rem; }}
.plain-table th {{ text-align: left; color: {MUTED}; font-weight: 600; border-bottom: 1px solid {BORDER}; padding: 6px 8px; }}
.plain-table td {{ padding: 6px 8px; border-bottom: 1px solid #f1f5f9; }}
@media (max-width: 640px) {{ .block-container {{ padding: .8rem .8rem 2rem; }} }}
</style>
"""


def logo_html() -> str:
    """Wordmark: two overlapping dollar signs (blue + green) followed by the name."""
    return ("<span class='logo'><span class='logo-mark'><span class='lm-a'>&#36;</span><span class='lm-b'>&#36;</span></span>"
            "<span class='logo-name'>Stock<span style='color:#2563eb'>Scout</span></span></span>")


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
