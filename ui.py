from html import escape

import streamlit as st

from branding import DEFAULT_PROFILE, logo_file

INK = "#172033"
RED = "#8C1C1C"
GREEN = "#0B8F55"


def profile():
    return st.session_state.get("company_profile", DEFAULT_PROFILE)


def apply_theme(company=None):
    company = company or profile()
    primary = company.get("primary_color", RED)
    secondary = company.get("secondary_color", INK)
    accent = company.get("accent_color", GREEN)
    st.markdown(f"""
    <style>
    :root{{--primary:{primary};--secondary:{secondary};--accent:{accent};}}
    .stApp{{background:#F4F6F8;color:#172033}}
    [data-testid="stSidebar"]{{background:linear-gradient(180deg,#111827,#0B1220)}}
    [data-testid="stSidebar"] *{{color:#F8FAFC}}
    [data-testid="stSidebar"] .stRadio label{{padding:.45rem .58rem;border-radius:.55rem}}
    .block-container{{padding-top:1.25rem;padding-bottom:3rem;max-width:1560px}}
    h1,h2,h3{{color:#172033;letter-spacing:-.025em}}
    .stButton>button,.stDownloadButton>button{{border-radius:9px;font-weight:650;min-height:2.65rem}}
    .stButton>button[kind="primary"]{{background:{primary};border-color:{primary}}}
    [data-testid="stMetric"],.product-card{{background:white;border:1px solid #E4E8EE;border-radius:14px;
      padding:17px 19px;box-shadow:0 7px 24px rgba(15,23,42,.055)}}
    div[data-testid="stDataFrame"]{{border:1px solid #E4E8EE;border-radius:12px;overflow:hidden}}
    .page-head{{display:flex;justify-content:space-between;align-items:center;gap:1rem;background:white;
      border:1px solid #E4E8EE;border-left:5px solid {primary};padding:19px 22px;border-radius:14px;margin-bottom:1.15rem}}
    .page-head h1{{font-size:1.55rem;margin:0}} .page-head p{{color:#64748B;margin:.25rem 0 0}}
    .user-chip{{background:{primary}12;color:{primary};padding:7px 12px;border-radius:999px;font-weight:700;font-size:.78rem}}
    .stat{{background:white;border:1px solid #E4E8EE;border-radius:14px;padding:18px;min-height:125px;
      box-shadow:0 7px 24px rgba(15,23,42,.05)}}
    .stat-label{{color:#64748B;font-size:.72rem;font-weight:750;letter-spacing:.075em;text-transform:uppercase}}
    .stat-value{{font-size:1.72rem;font-weight:780;margin:.38rem 0;color:#111827}} .stat-note{{color:#64748B;font-size:.79rem}}
    .action-card{{background:white;border:1px solid #E4E8EE;border-radius:14px;padding:17px;min-height:105px}}
    .action-title{{font-weight:760;font-size:1rem;color:#172033}} .action-note{{color:#64748B;font-size:.8rem;margin-top:.28rem}}
    .eyebrow{{color:{primary};font-size:.73rem;font-weight:800;letter-spacing:.1em;text-transform:uppercase}}
    </style>""", unsafe_allow_html=True)


def render_sidebar_brand(company=None):
    company = company or profile()
    logo = logo_file(company)
    if logo:
        st.sidebar.image(str(logo), width=180)
    else:
        st.sidebar.markdown(f"## {escape(company['company_name'])}")
    st.sidebar.caption(escape(company.get("application_name", "Fuel Inventory Control")).upper())


def page_header(title, subtitle):
    user = escape(str(st.session_state.get("user", "User")))
    role = escape(str(st.session_state.get("role", "")).title())
    st.markdown(f'<div class="page-head"><div><h1>{escape(title)}</h1><p>{escape(subtitle)}</p></div>'
                f'<span class="user-chip">{user} · {role}</span></div>', unsafe_allow_html=True)


def stat_card(label, value, note=""):
    st.markdown(f'<div class="stat"><div class="stat-label">{escape(str(label))}</div>'
                f'<div class="stat-value">{escape(str(value))}</div><div class="stat-note">{escape(str(note))}</div></div>',
                unsafe_allow_html=True)


def action_card(title, note):
    st.markdown(f'<div class="action-card"><div class="action-title">{escape(title)}</div>'
                f'<div class="action-note">{escape(note)}</div></div>', unsafe_allow_html=True)
