from pathlib import Path

import streamlit as st


INK = "#171717"
RED = "#8C1C1C"
GREEN = "#05AF52"


def apply_theme() -> None:
    st.markdown(
        """
        <style>
        :root { --fillit-ink:#171717; --fillit-red:#8C1C1C; --fillit-green:#05AF52; }
        .stApp { background:#F6F6F4; color:#242424; }
        [data-testid="stSidebar"] { background:linear-gradient(180deg,#171717 0%,#0C0C0C 100%); }
        [data-testid="stSidebar"] * { color:#F8FAFC; }
        [data-testid="stSidebar"] .stRadio label { padding:.34rem .48rem; border-radius:.55rem; }
        [data-testid="stMetric"] { background:#FFFFFF; border:1px solid #E8E4E1; border-radius:12px;
            padding:16px 18px; box-shadow:0 4px 18px rgba(23,23,23,.05); }
        [data-testid="stMetricValue"] { color:#171717; font-weight:750; }
        .stButton>button, .stDownloadButton>button { border-radius:9px; font-weight:650; min-height:2.65rem; }
        .stButton>button[kind="primary"] { background:#8C1C1C; border-color:#8C1C1C; }
        div[data-testid="stDataFrame"] { border:1px solid #E3EAF2; border-radius:12px; overflow:hidden; }
        h1,h2,h3 { color:#171717; letter-spacing:-.025em; }
        .fillit-page-head { display:flex; align-items:center; justify-content:space-between; gap:1rem;
            background:#fff; border:1px solid #E8E4E1; border-left:5px solid #8C1C1C;
            padding:18px 22px; border-radius:14px; margin:0 0 1.2rem 0; }
        .fillit-page-head h1 { font-size:1.55rem; margin:0; }
        .fillit-page-head p { margin:.2rem 0 0; color:#64748B; }
        .fillit-user-chip { background:#F7EDED; color:#8C1C1C; padding:7px 11px; border-radius:999px;
            font-size:.78rem; font-weight:700; white-space:nowrap; }
        .fillit-stat { background:#fff; border:1px solid #E8E4E1; border-radius:14px; padding:18px;
            min-height:132px; box-shadow:0 5px 22px rgba(23,23,23,.05); }
        .fillit-stat-label { color:#777; font-size:.77rem; font-weight:700; letter-spacing:.07em; text-transform:uppercase; }
        .fillit-stat-value { color:#171717; font-size:1.75rem; font-weight:780; margin:.35rem 0 .2rem; }
        .fillit-stat-note { color:#777; font-size:.78rem; }
        .fillit-alert { background:#FFF7F2; border:1px solid #F2D8CC; border-radius:12px; padding:14px 16px; }
        .block-container { padding-top:1.5rem; padding-bottom:3rem; max-width:1500px; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar_brand() -> None:
    logo = Path(__file__).parent / "assets" / "fillit-logo.png"
    if logo.exists():
        st.sidebar.image(str(logo), width=185)
    st.sidebar.caption("CORPORATE FUEL OPERATIONS")


def page_header(title: str, subtitle: str) -> None:
    user = st.session_state.get("user", "User")
    role = st.session_state.get("role", "")
    st.markdown(
        f'<div class="fillit-page-head"><div><h1>{title}</h1><p>{subtitle}</p></div>'
        f'<span class="fillit-user-chip">{user} · {role.title()}</span></div>',
        unsafe_allow_html=True,
    )


def stat_card(label: str, value: str, note: str = "") -> None:
    st.markdown(
        f'<div class="fillit-stat"><div class="fillit-stat-label">{label}</div>'
        f'<div class="fillit-stat-value">{value}</div><div class="fillit-stat-note">{note}</div></div>',
        unsafe_allow_html=True,
    )
