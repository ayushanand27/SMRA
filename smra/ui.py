"""Premium dark ("black") UI theme and reusable render helpers for the Streamlit app.

Kept separate from app.py so styling can evolve without touching agent logic.
"""
import streamlit as st

# Route accent colors (used for badges and glows).
ROUTE_COLORS = {
    "SQL": "#3b82f6",     # blue
    "RAG": "#8b5cf6",     # violet
    "WEB": "#f59e0b",     # amber
    "HYBRID": "#10b981",  # emerald
}

ROUTE_ICONS = {
    "SQL": "table",
    "RAG": "file-text",
    "WEB": "globe",
    "HYBRID": "layers",
}

PREMIUM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
    --bg: #0a0a0f;
    --bg-soft: #0f0f16;
    --panel: #14141c;
    --panel-2: #1a1a24;
    --border: rgba(255,255,255,0.08);
    --border-strong: rgba(255,255,255,0.14);
    --text: #e6e6ef;
    --text-dim: #9a9aae;
    --accent: #10b981;
    --accent-2: #06b6d4;
    --glow: rgba(16,185,129,0.35);
}

/* Base */
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.stApp {
    background:
        radial-gradient(1200px 600px at 15% -10%, rgba(16,185,129,0.10), transparent 55%),
        radial-gradient(1000px 500px at 110% 10%, rgba(99,102,241,0.10), transparent 50%),
        var(--bg);
    color: var(--text);
}

/* Hide default Streamlit chrome */
#MainMenu, header[data-testid="stHeader"], footer { visibility: hidden; }
[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 2.2rem; padding-bottom: 6rem; max-width: 1150px; }

/* Hero header */
.smra-hero {
    position: relative;
    border: 1px solid var(--border);
    border-radius: 22px;
    padding: 26px 30px;
    margin-bottom: 22px;
    background:
        linear-gradient(135deg, rgba(16,185,129,0.12), rgba(6,182,212,0.05) 40%, rgba(0,0,0,0) 70%),
        var(--panel);
    box-shadow: 0 20px 60px rgba(0,0,0,0.45), inset 0 1px 0 rgba(255,255,255,0.04);
    overflow: hidden;
}
.smra-hero::after {
    content: ""; position: absolute; inset: 0;
    background: radial-gradient(600px 200px at 80% -40%, var(--glow), transparent 60%);
    opacity: 0.5; pointer-events: none;
}
.smra-hero h1 {
    font-size: 30px; font-weight: 800; letter-spacing: -0.02em; margin: 0;
    background: linear-gradient(90deg, #ffffff, #bdf5df 60%, #7fe7cf);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
}
.smra-hero p { color: var(--text-dim); margin: 8px 0 0; font-size: 14.5px; }
.smra-badge-row { margin-top: 16px; display: flex; gap: 8px; flex-wrap: wrap; }
.smra-pill {
    display: inline-flex; align-items: center; gap: 6px;
    font-size: 12px; font-weight: 600; color: var(--text-dim);
    border: 1px solid var(--border); border-radius: 999px;
    padding: 5px 12px; background: rgba(255,255,255,0.02);
}
.smra-pill .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 8px var(--glow); }

/* Sidebar */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0c0c12, #0a0a0f);
    border-right: 1px solid var(--border);
}
[data-testid="stSidebar"] .block-container { padding-top: 1.5rem; }
.smra-side-title {
    font-size: 12px; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase;
    color: var(--text-dim); margin: 6px 0 14px;
}
.smra-metric {
    border: 1px solid var(--border); border-radius: 14px; padding: 14px 16px; margin-bottom: 10px;
    background: linear-gradient(180deg, var(--panel-2), var(--panel));
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.03);
    transition: border-color .2s ease, transform .2s ease;
}
.smra-metric:hover { border-color: var(--border-strong); transform: translateY(-1px); }
.smra-metric .label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: var(--text-dim); }
.smra-metric .value { font-size: 22px; font-weight: 800; margin-top: 4px; color: #fff; }
.smra-metric .value .unit { font-size: 12px; font-weight: 600; color: var(--accent); margin-left: 6px; }

/* Route badges */
.smra-routes { display: flex; gap: 8px; flex-wrap: wrap; margin: 4px 0 10px; }
.smra-route {
    display: inline-flex; align-items: center; gap: 7px;
    font-size: 12.5px; font-weight: 700; letter-spacing: 0.02em;
    padding: 6px 13px; border-radius: 10px; color: #fff;
    border: 1px solid var(--rc, var(--accent));
    background: color-mix(in srgb, var(--rc, var(--accent)) 16%, transparent);
    box-shadow: 0 0 0 1px rgba(0,0,0,0.2), 0 6px 18px color-mix(in srgb, var(--rc, var(--accent)) 22%, transparent);
}
.smra-route .rdot { width: 8px; height: 8px; border-radius: 50%; background: var(--rc, var(--accent)); box-shadow: 0 0 10px var(--rc, var(--accent)); }

/* Chat messages */
[data-testid="stChatMessage"] {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 16px 18px;
    box-shadow: 0 10px 30px rgba(0,0,0,0.35);
    margin-bottom: 4px;
}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
    background: linear-gradient(180deg, rgba(16,185,129,0.08), var(--panel));
    border-color: rgba(16,185,129,0.22);
}

/* Chat input */
[data-testid="stChatInput"] {
    border: 1px solid var(--border-strong);
    border-radius: 16px;
    background: var(--panel);
    box-shadow: 0 12px 40px rgba(0,0,0,0.5);
}
[data-testid="stChatInput"] textarea { color: var(--text) !important; }
[data-testid="stChatInput"]:focus-within {
    border-color: var(--accent);
    box-shadow: 0 0 0 3px rgba(16,185,129,0.18), 0 12px 40px rgba(0,0,0,0.5);
}

/* Expanders */
[data-testid="stExpander"] {
    border: 1px solid var(--border) !important;
    border-radius: 14px !important;
    background: var(--bg-soft) !important;
    overflow: hidden;
}
[data-testid="stExpander"] summary { font-weight: 600; color: var(--text-dim); }
[data-testid="stExpander"] summary:hover { color: var(--text); }

/* Source cards */
.smra-src {
    display: block; text-decoration: none !important;
    border: 1px solid var(--border); border-radius: 12px;
    padding: 11px 14px; margin-bottom: 8px;
    background: var(--panel);
    transition: border-color .18s ease, transform .18s ease, background .18s ease;
}
.smra-src:hover { border-color: var(--accent); transform: translateX(2px); background: var(--panel-2); }
.smra-src .idx { color: var(--accent); font-weight: 700; font-family: 'JetBrains Mono', monospace; margin-right: 8px; }
.smra-src .t { color: var(--text); font-weight: 600; font-size: 13.5px; }
.smra-src .u { color: var(--text-dim); font-size: 12px; display: block; margin-top: 2px; word-break: break-all; }
.smra-src-h { font-size: 12px; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; color: var(--text-dim); margin: 6px 0 10px; }

/* Grounding chips */
.smra-chip {
    display: inline-flex; align-items: center; gap: 6px;
    font-size: 12px; font-weight: 600; padding: 4px 11px; border-radius: 999px;
    border: 1px solid var(--border); background: rgba(255,255,255,0.02); color: var(--text-dim);
}
.smra-chip.ok { color: #34d399; border-color: rgba(52,211,153,0.35); background: rgba(52,211,153,0.08); }
.smra-chip.warn { color: #fbbf24; border-color: rgba(251,191,36,0.35); background: rgba(251,191,36,0.08); }

/* Disclaimer */
.smra-disc {
    margin-top: 14px; font-size: 12.5px; color: var(--text-dim);
    border: 1px dashed var(--border-strong); border-radius: 12px; padding: 10px 14px;
    background: rgba(255,255,255,0.015);
}

/* Progress bar accent */
[data-testid="stProgress"] > div > div > div { background: linear-gradient(90deg, var(--accent), var(--accent-2)) !important; }

/* Code blocks */
code, pre, .stCode { font-family: 'JetBrains Mono', monospace !important; }
</style>
"""


def inject_theme() -> None:
    st.markdown(PREMIUM_CSS, unsafe_allow_html=True)


def render_hero(provider: str) -> None:
    st.markdown(
        f"""
        <div class="smra-hero">
            <h1>SMRA — Stock Market Research Assistant</h1>
            <p>Institutional-grade research across market data, filings, and live news — routed, cited, and audited.</p>
            <div class="smra-badge-row">
                <span class="smra-pill"><span class="dot"></span>Text-to-SQL</span>
                <span class="smra-pill"><span class="dot"></span>Hybrid RAG + Rerank</span>
                <span class="smra-pill"><span class="dot"></span>Live Web</span>
                <span class="smra-pill"><span class="dot"></span>Provider: {provider}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metric(label: str, value, unit: str = "") -> None:
    unit_html = f'<span class="unit">{unit}</span>' if unit else ""
    st.markdown(
        f"""
        <div class="smra-metric">
            <div class="label">{label}</div>
            <div class="value">{value}{unit_html}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_route_badges(routes: list[str]) -> None:
    chips = []
    for r in routes:
        color = ROUTE_COLORS.get(r.upper(), ROUTE_COLORS["HYBRID"])
        chips.append(
            f'<span class="smra-route" style="--rc:{color}"><span class="rdot"></span>{r.upper()}</span>'
        )
    st.markdown(f'<div class="smra-routes">{"".join(chips)}</div>', unsafe_allow_html=True)


def render_sources(sources: list, title: str = "Sources", limit: int = 8) -> None:
    if not sources:
        return
    st.markdown(f'<div class="smra-src-h">{title}</div>', unsafe_allow_html=True)
    for idx, src in enumerate(sources[:limit], start=1):
        src = str(src)
        if src.startswith("http"):
            html = (
                f'<a class="smra-src" href="{src}" target="_blank">'
                f'<span class="idx">{idx:02d}</span><span class="u">{src}</span></a>'
            )
        else:
            import os

            name = os.path.basename(src) or src
            html = (
                f'<div class="smra-src"><span class="idx">{idx:02d}</span>'
                f'<span class="t">{name}</span></div>'
            )
        st.markdown(html, unsafe_allow_html=True)


def render_grounding(meta: dict) -> None:
    if not isinstance(meta, dict):
        return
    grounded = meta.get("grounded")
    score = meta.get("faithfulness_score")
    if grounded is None and score is None:
        return
    if grounded:
        st.markdown(
            f'<span class="smra-chip ok">✓ Grounded · {score}</span>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<span class="smra-chip warn">⚠ Unverified figures · {score}</span>',
            unsafe_allow_html=True,
        )


def render_disclaimer() -> None:
    st.markdown(
        '<div class="smra-disc">⚠️ Educational/research use only — not financial advice. '
        "Consult a licensed advisor before investing.</div>",
        unsafe_allow_html=True,
    )


def style_plotly(fig):
    """Apply the dark premium theme to a Plotly figure."""
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, sans-serif", color="#c8c8d6", size=12),
        margin=dict(l=10, r=10, t=30, b=10),
        xaxis=dict(gridcolor="rgba(255,255,255,0.06)", zerolinecolor="rgba(255,255,255,0.08)"),
        yaxis=dict(gridcolor="rgba(255,255,255,0.06)", zerolinecolor="rgba(255,255,255,0.08)"),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
    )
    fig.update_traces(line=dict(color="#10b981", width=2.5))
    return fig
