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
    :root{{--primary:{primary};--secondary:{secondary};--accent:{accent};--ink:#111827;--muted:#667085;--line:#E4E7EC;--canvas:#F3F5F8;}}
    html,body,[class*="css"]{{font-family:Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
    .stApp{{background:radial-gradient(circle at 88% 0%,{primary}0A 0,transparent 24rem),var(--canvas);color:var(--ink)}}
    [data-testid="stHeader"]{{background:rgba(243,245,248,.88);backdrop-filter:blur(10px);border-bottom:1px solid rgba(228,231,236,.8)}}
    [data-testid="stSidebar"]{{background:linear-gradient(180deg,#111827 0%,#0B1220 55%,#080D18 100%);border-right:1px solid #263244;transition:width .22s ease,min-width .22s ease,max-width .22s ease,transform .22s ease}}
    [data-testid="stSidebar"][aria-expanded="true"]{{width:292px!important;min-width:292px!important;max-width:292px!important}}
    [data-testid="stSidebar"][aria-expanded="false"]{{width:0!important;min-width:0!important;max-width:0!important;border-right:0!important;overflow:hidden!important}}
    [data-testid="stSidebarCollapsedControl"],[data-testid="collapsedControl"]{{position:fixed!important;left:.7rem!important;top:.55rem!important;z-index:100000!important;margin:0!important;transform:none!important}}
    [data-testid="stSidebar"]>div:first-child{{padding:1rem .8rem 1.2rem}}
    [data-testid="stSidebar"] *{{color:#F8FAFC}}
    [data-testid="stSidebar"] [data-testid="stExpander"]{{border:0;background:transparent}}
    [data-testid="stSidebar"] [data-testid="stExpander"] details{{border:0}}
    [data-testid="stSidebar"] [data-testid="stExpander"] summary{{font-size:.69rem;font-weight:800;letter-spacing:.09em;text-transform:uppercase;color:#98A2B3;padding:.7rem .35rem .35rem}}
    [data-testid="stSidebar"] [data-testid="stExpander"] details[open]>summary{{background:linear-gradient(90deg,{primary}38,#1D2939 72%);color:#FFFFFF!important;border:1px solid {primary}72;border-left:4px solid {primary};border-radius:10px;padding:.68rem .72rem;margin:.2rem 0 .45rem;box-shadow:0 7px 18px rgba(0,0,0,.16)}}
    [data-testid="stSidebar"] [data-testid="stExpander"] details[open]>summary *{{color:#FFFFFF!important;fill:#FFFFFF!important}}
    [data-testid="stSidebar"] [data-testid="stExpander"] details:not([open])>summary:hover{{background:#FFFFFF0B;color:#FFFFFF;border-radius:9px}}
    [data-testid="stSidebar"] .stButton>button{{justify-content:flex-start;text-align:left;background:transparent;border:1px solid transparent;color:#D7DEE9;box-shadow:none;min-height:2.25rem;padding:.42rem .65rem}}
    [data-testid="stSidebar"] .stButton>button:hover{{background:#FFFFFF0D;border-color:#FFFFFF16;color:white;transform:none}}
    [data-testid="stSidebar"] .stButton>button[kind="primary"]{{background:linear-gradient(135deg,{primary},#B52B2B);border-color:#D95C5C;color:white;box-shadow:0 8px 22px {primary}50}}
    .sidebar-brand{{background:#FFFFFF0A;border:1px solid #FFFFFF12;border-radius:16px;padding:12px;margin-bottom:.7rem}}
    .sidebar-product{{font-size:.67rem;color:#98A2B3;letter-spacing:.11em;text-transform:uppercase;font-weight:800;margin-top:.55rem}}
    .sidebar-tagline{{font-size:.71rem;color:#667085;line-height:1.35;margin-top:.15rem}}
    .block-container{{padding-top:1.05rem;padding-bottom:3.5rem;max-width:none!important;width:100%!important}}
    h1,h2,h3{{color:var(--ink);letter-spacing:-.035em;font-weight:750}} h2{{font-size:1.35rem}} h3{{font-size:1.06rem}}
    p,.stCaption{{color:var(--muted)}}
    .stButton>button,.stDownloadButton>button{{border-radius:10px;font-weight:680;min-height:2.55rem;border:1px solid #D0D5DD;transition:.16s ease;box-shadow:0 1px 2px rgba(16,24,40,.04)}}
    .stButton>button:hover,.stDownloadButton>button:hover{{border-color:{primary};color:{primary};transform:translateY(-1px);box-shadow:0 7px 18px rgba(16,24,40,.08)}}
    .stButton>button[kind="primary"]{{background:linear-gradient(135deg,{primary},#A92626);border-color:{primary};color:white;box-shadow:0 7px 18px {primary}35}}
    [data-testid="stMetric"]{{background:linear-gradient(145deg,#FFFFFF,#FBFCFD);border:1px solid var(--line);border-radius:16px;padding:18px 20px;box-shadow:0 10px 28px rgba(16,24,40,.055)}}
    [data-testid="stMetricLabel"]{{color:#667085;font-weight:650}} [data-testid="stMetricValue"]{{color:#101828;font-weight:760;letter-spacing:-.04em}}
    [data-testid="stForm"]{{background:#FFFFFF;border:1px solid var(--line);border-radius:16px;padding:1.2rem;box-shadow:0 8px 24px rgba(16,24,40,.045)}}
    [data-baseweb="input"]>div,[data-baseweb="select"]>div,[data-baseweb="textarea"]>div{{border-radius:10px!important;border-color:#D0D5DD!important;background:#FCFCFD!important}}
    [data-baseweb="tab-list"]{{gap:.35rem;background:#EAECF0;padding:.28rem;border-radius:12px}}
    [data-baseweb="tab"]{{border-radius:9px;padding:.6rem .9rem;border:0}}
    [aria-selected="true"][data-baseweb="tab"]{{background:white;color:{primary};box-shadow:0 2px 7px rgba(16,24,40,.09)}}
    div[data-testid="stDataFrame"]{{border:1px solid var(--line);border-radius:14px;overflow:hidden;box-shadow:0 7px 22px rgba(16,24,40,.04)}}
    [data-testid="stAlert"]{{border-radius:12px;border-width:1px}}
    hr{{border-color:var(--line)!important;margin:1.2rem 0!important}}
    .page-head{{position:relative;overflow:hidden;display:flex;justify-content:space-between;align-items:center;gap:1rem;background:linear-gradient(120deg,#FFFFFF 0%,#FFFFFF 70%,{primary}08 100%);border:1px solid var(--line);padding:22px 25px;border-radius:18px;margin-bottom:1.2rem;box-shadow:0 10px 30px rgba(16,24,40,.055)}}
    .page-head:before{{content:"";position:absolute;left:0;top:0;bottom:0;width:5px;background:linear-gradient(180deg,{primary},#D74B4B)}}
    .page-head h1{{font-size:1.62rem;margin:0}} .page-head p{{color:#667085;margin:.3rem 0 0;font-size:.88rem}}
    .page-context{{display:flex;align-items:center;gap:.6rem}} .live-dot{{width:8px;height:8px;border-radius:50%;background:{accent};box-shadow:0 0 0 5px {accent}18}}
    .user-chip{{background:#FFFFFF;border:1px solid #E4E7EC;color:#344054;padding:8px 12px;border-radius:999px;font-weight:700;font-size:.75rem;white-space:nowrap}}
    .stat{{position:relative;overflow:hidden;background:linear-gradient(145deg,#FFFFFF,#FBFCFD);border:1px solid var(--line);border-radius:16px;padding:18px 19px;min-height:126px;box-shadow:0 10px 28px rgba(16,24,40,.055)}}
    .stat:after{{content:"";position:absolute;width:78px;height:78px;border-radius:50%;right:-34px;top:-34px;background:{primary}0D}}
    .stat-label{{color:#667085;font-size:.68rem;font-weight:800;letter-spacing:.09em;text-transform:uppercase}}
    .stat-value{{font-size:1.75rem;font-weight:780;margin:.42rem 0;color:#101828;letter-spacing:-.04em}} .stat-note{{color:#667085;font-size:.76rem}}
    .command-shell{{background:linear-gradient(130deg,#101828 0%,#17233A 62%,{primary} 150%);border:1px solid #344054;color:white;border-radius:22px;padding:32px 34px;min-height:220px;box-shadow:0 22px 55px rgba(16,24,40,.22);position:relative;overflow:hidden}}
    .command-shell:after{{content:"";position:absolute;right:-100px;top:-150px;width:360px;height:360px;border-radius:50%;border:70px solid rgba(255,255,255,.035)}}
    .hero-kicker{{font-size:.68rem;font-weight:850;letter-spacing:.15em;color:#D0D5DD}}
    .hero-title{{font-size:2.28rem;line-height:1.08;font-weight:790;max-width:700px;margin:.72rem 0;letter-spacing:-.045em}}
    .hero-copy{{color:#CDD5E1;max-width:720px;line-height:1.6;font-size:.91rem}}
    .hero-meta{{display:flex;gap:1rem;margin-top:1.35rem;color:#98A2B3;font-size:.72rem}} .hero-meta b{{color:white}}
    .control-panel{{background:#FFFFFF;border:1px solid var(--line);border-radius:22px;padding:24px;min-height:220px;box-shadow:0 16px 40px rgba(16,24,40,.08)}}
    .control-label{{color:{primary};font-size:.67rem;font-weight:850;letter-spacing:.13em;text-transform:uppercase}}
    .control-date{{font-size:1.45rem;font-weight:780;color:#101828;margin:.7rem 0 .2rem}} .control-copy{{color:#667085;font-size:.78rem;line-height:1.45}}
    .health-ring{{margin-top:1rem;height:7px;background:#EAECF0;border-radius:99px;overflow:hidden}} .health-ring span{{display:block;height:100%;background:linear-gradient(90deg,{accent},#42C98A);border-radius:99px}}
    .section-label{{font-size:.68rem;font-weight:850;letter-spacing:.12em;color:#667085;margin:1.45rem 0 .7rem;text-transform:uppercase}}
    .workspace-card{{background:#FFFFFF;border:1px solid var(--line);border-radius:16px 16px 0 0;padding:18px 18px 12px;min-height:112px;transition:.16s ease}}
    .workspace-card:hover{{border-color:#C8CDD5;box-shadow:0 12px 28px rgba(16,24,40,.07)}}
    .workspace-icon{{width:34px;height:34px;border-radius:10px;background:{primary}0D;color:{primary};display:flex;align-items:center;justify-content:center;font-size:1rem;margin-bottom:.7rem}}
    .workspace-title{{font-size:.94rem;font-weight:760;color:#101828}} .workspace-copy{{font-size:.76rem;color:#667085;line-height:1.42;margin-top:.32rem}}
    .panel{{background:white;border:1px solid var(--line);border-radius:17px;padding:20px;box-shadow:0 9px 25px rgba(16,24,40,.045)}}
    .operations-intro{{display:flex;align-items:center;justify-content:space-between;gap:1rem;background:linear-gradient(120deg,#FFFFFF,#F8FAFC);border:1px solid var(--line);border-radius:16px;padding:16px 19px;margin:.2rem 0 1rem}}
    .operations-intro b{{display:block;color:#101828;font-size:.92rem}} .operations-intro span{{color:#667085;font-size:.76rem}}
    .operations-badge{{background:{primary}0E;color:{primary};border:1px solid {primary}25;border-radius:999px;padding:.45rem .75rem;font-size:.68rem;font-weight:800;letter-spacing:.07em;white-space:nowrap}}
    .workflow-rail{{background:#101828;border:1px solid #344054;border-radius:18px;padding:15px 16px 10px;margin:.8rem 0 1.2rem;box-shadow:0 16px 36px rgba(16,24,40,.16)}}
    .workflow-rail-title{{color:#98A2B3;font-size:.64rem;font-weight:850;letter-spacing:.12em;text-transform:uppercase;margin:0 0 .7rem .15rem}}
    .workflow-tile{{position:relative;background:#1D2939;border:1px solid #344054;border-radius:13px 13px 0 0;padding:13px 13px 10px;min-height:89px;overflow:hidden}}
    .workflow-tile.active{{background:linear-gradient(135deg,{primary},#B82C2C);border-color:#E36B6B;box-shadow:0 9px 24px {primary}42}}
    .workflow-number{{font-size:.62rem;color:#98A2B3;font-weight:850;letter-spacing:.1em}} .workflow-tile.active .workflow-number{{color:#FFFFFFB8}}
    .workflow-name{{font-size:.84rem;color:#F9FAFB;font-weight:760;margin-top:.35rem}} .workflow-description{{font-size:.66rem;color:#98A2B3;line-height:1.3;margin-top:.22rem}} .workflow-tile.active .workflow-description{{color:#FFFFFFC9}}
    .workspace-canvas{{background:linear-gradient(145deg,#FFFFFF,#FBFCFD);border:1px solid var(--line);border-radius:18px;padding:20px 22px;margin-top:.35rem;box-shadow:0 12px 32px rgba(16,24,40,.055)}}
    .balance-panel{{display:grid;grid-template-columns:1.45fr 1fr 1fr;gap:1rem;background:linear-gradient(135deg,#101828,#1D2939);color:white;border-radius:16px;padding:18px 20px;margin:.8rem 0 1.1rem;box-shadow:0 14px 32px rgba(16,24,40,.16)}}
    .balance-panel small{{display:block;color:#98A2B3;font-size:.65rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase;margin-bottom:.28rem}} .balance-panel strong{{font-size:1.35rem;letter-spacing:-.03em}} .balance-panel span{{display:block;color:#D0D5DD;font-size:.78rem;margin-top:.25rem}}
    .balance-panel .positive{{color:#6CE9A6}} .balance-panel .warning{{color:#FDB022}}
    .form-section-title{{font-size:.72rem;color:#475467;font-weight:800;letter-spacing:.09em;text-transform:uppercase;margin:.4rem 0 .65rem}}
    .history-heading{{display:flex;justify-content:space-between;align-items:center;margin:1.2rem 0 .6rem}} .history-heading b{{font-size:.95rem;color:#101828}} .history-heading span{{font-size:.7rem;color:#667085}}
    .queue-item{{display:flex;justify-content:space-between;align-items:center;background:#FCFCFD;border:1px solid var(--line);border-left:4px solid #F79009;border-radius:11px;padding:12px 13px;margin-bottom:.5rem}}
    .queue-item.critical{{border-left-color:#D92D20}} .queue-item span{{font-size:.75rem;color:#667085}} .queue-item strong{{font-size:.63rem;letter-spacing:.09em;color:#B54708}}
    .timeline-row{{display:flex;gap:.75rem;padding:.68rem .1rem;border-bottom:1px solid #F0F2F5}} .timeline-dot{{width:8px;height:8px;border-radius:50%;background:{primary};margin-top:.38rem;flex:none;box-shadow:0 0 0 4px {primary}12}}
    .timeline-row b{{display:block;font-size:.78rem}} .timeline-row span{{display:block;color:#475467;font-size:.74rem;line-height:1.35;max-height:2.1rem;overflow:hidden}} .timeline-row small{{color:#98A2B3;font-size:.65rem}}
    @media(max-width:900px){{[data-testid="stSidebar"][aria-expanded="true"]{{width:255px!important;min-width:255px!important;max-width:255px!important}}.block-container{{padding-left:1rem;padding-right:1rem}}.hero-title{{font-size:1.7rem}}.command-shell,.control-panel{{min-height:auto}}.page-head{{align-items:flex-start;flex-direction:column}}.balance-panel{{grid-template-columns:1fr}}}}
    </style>""", unsafe_allow_html=True)


def render_sidebar_brand(company=None):
    company = company or profile()
    logo = logo_file(company)
    st.sidebar.markdown('<div class="sidebar-brand">',unsafe_allow_html=True)
    if logo: st.sidebar.image(str(logo), width=168)
    else: st.sidebar.markdown(f"### {escape(company['company_name'])}")
    st.sidebar.markdown(f'<div class="sidebar-product">{escape(company.get("application_name","Fuel Inventory Control"))}</div><div class="sidebar-tagline">{escape(company.get("tagline", "Controlled inventory intelligence"))}</div>',unsafe_allow_html=True)
    st.sidebar.markdown('</div>',unsafe_allow_html=True)


def page_header(title, subtitle):
    user = escape(str(st.session_state.get("user", "User")))
    role = escape(str(st.session_state.get("role", "")).title())
    st.markdown(f'<div class="page-head"><div><h1>{escape(title)}</h1><p>{escape(subtitle)}</p></div>'
                f'<div class="page-context"><span class="live-dot"></span><span class="user-chip">{user} · {role}</span></div></div>', unsafe_allow_html=True)


def stat_card(label, value, note=""):
    st.markdown(f'<div class="stat"><div class="stat-label">{escape(str(label))}</div>'
                f'<div class="stat-value">{escape(str(value))}</div><div class="stat-note">{escape(str(note))}</div></div>',
                unsafe_allow_html=True)


def action_card(title, note):
    st.markdown(f'<div class="action-card"><div class="action-title">{escape(title)}</div>'
                f'<div class="action-note">{escape(note)}</div></div>', unsafe_allow_html=True)
