from pathlib import Path

import streamlit as st


NAVY = "#0B1F33"
RED = "#D62839"
TEAL = "#14B8A6"


def apply_theme() -> None:
    st.markdown(
        """
        <style>
        :root { --fillit-navy:#0B1F33; --fillit-red:#D62839; --fillit-teal:#14B8A6; }
        .stApp { background:#F4F7FA; color:#172033; }
        [data-testid="stSidebar"] { background:linear-gradient(180deg,#081827 0%,#0B1F33 100%); }
        [data-testid="stSidebar"] * { color:#F8FAFC; }
        [data-testid="stSidebar"] .stRadio label { padding:.34rem .48rem; border-radius:.55rem; }
        [data-testid="stMetric"] { background:#FFFFFF; border:1px solid #E3EAF2; border-radius:14px;
            padding:16px 18px; box-shadow:0 3px 14px rgba(11,31,51,.06); }
        [data-testid="stMetricValue"] { color:#0B1F33; font-weight:750; }
        .stButton>button, .stDownloadButton>button { border-radius:9px; font-weight:650; min-height:2.65rem; }
        .stButton>button[kind="primary"] { background:#D62839; border-color:#D62839; }
        div[data-testid="stDataFrame"] { border:1px solid #E3EAF2; border-radius:12px; overflow:hidden; }
        h1,h2,h3 { color:#0B1F33; letter-spacing:-.02em; }
        .fillit-page-head { display:flex; align-items:center; justify-content:space-between; gap:1rem;
            background:#fff; border:1px solid #E3EAF2; border-left:5px solid #D62839;
            padding:18px 22px; border-radius:14px; margin:0 0 1.2rem 0; }
        .fillit-page-head h1 { font-size:1.55rem; margin:0; }
        .fillit-page-head p { margin:.2rem 0 0; color:#64748B; }
        .fillit-user-chip { background:#E8F7F5; color:#087F72; padding:7px 11px; border-radius:999px;
            font-size:.78rem; font-weight:700; white-space:nowrap; }
        .block-container { padding-top:1.5rem; padding-bottom:3rem; max-width:1500px; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar_brand() -> None:
    logo = Path(__file__).parent / "assets" / "fillit-logo.png"
    if logo.exists():
        st.sidebar.image(str(logo), use_container_width=True)
    st.sidebar.caption("FLEET FUEL CONTROL")


def page_header(title: str, subtitle: str) -> None:
    user = st.session_state.get("user", "User")
    role = st.session_state.get("role", "")
    st.markdown(
        f'<div class="fillit-page-head"><div><h1>{title}</h1><p>{subtitle}</p></div>'
        f'<span class="fillit-user-chip">{user} · {role.title()}</span></div>',
        unsafe_allow_html=True,
    )
