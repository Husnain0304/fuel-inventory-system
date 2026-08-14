from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ui import GREEN, RED, page_header, profile, stat_card


def _read(conn, query, params=None):
    return pd.read_sql_query(query, conn, params=params or [])


def _go(label):
    st.session_state["navigation_target"] = label
    st.rerun()


def _launcher(title, description, destination, key, primary=False):
    st.markdown(
        f'<div class="launch-card"><div class="launch-title">{title}</div>'
        f'<div class="launch-copy">{description}</div></div>', unsafe_allow_html=True
    )
    if st.button("Open workspace", key=key, type="primary" if primary else "secondary", use_container_width=True):
        _go(destination)


def render_dashboard(conn, truck_dict, truck_list):
    company = profile()
    user = st.session_state.get("user", "User")
    today = date.today()
    page_header("Command Centre", f"Welcome back, {user}. Everything requiring attention is organised here.")

    hero_left, hero_right = st.columns([2.2, 1], gap="large")
    with hero_left:
        st.markdown(
            '<div class="command-hero"><div class="hero-kicker">LIVE INVENTORY CONTROL</div>'
            '<div class="hero-title">Run today’s fuel operations from one screen.</div>'
            '<div class="hero-copy">Record movements, review stock, investigate exceptions and produce management information without searching through menus.</div>'
            '</div>', unsafe_allow_html=True
        )
    with hero_right:
        st.markdown(
            f'<div class="today-panel"><div class="today-label">TODAY</div>'
            f'<div class="today-date">{today:%d %B %Y}</div>'
            f'<div class="today-company">{company["company_name"]} · {company["application_name"]}</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown('<div class="section-label">START AN OPERATION</div>', unsafe_allow_html=True)
    action_columns = st.columns(4, gap="medium")
    actions = [
        ("Record fuel movement", "Post an uplift or delivery and review the resulting balance.", "Fuel Operations", "launch_movement", True),
        ("Transfer inventory", "Move fuel safely between trucks with linked IN and OUT records.", "Fuel Operations", "launch_transfer", False),
        ("Reconcile physical stock", "Compare measured stock with the system and control adjustments.", "Inventory Control", "launch_reconcile", False),
        ("Storage operations", "Receive fuel, transfer tanks, load trucks and post returns.", "Storage Operations", "launch_storage_ops", False),
    ]
    for column, details in zip(action_columns, actions):
        with column:
            _launcher(*details)

    settings = _read(conn, "SELECT minimum_stock_level FROM settings ORDER BY id LIMIT 1")
    minimum = float(settings.iloc[0]["minimum_stock_level"] or 0) if not settings.empty else 0
    balances = _read(conn, """
        SELECT tr.id, CONCAT(tr.emirate,' ',tr.plate_code,' ',tr.plate_number) AS truck,
          COALESCE(SUM(CASE WHEN tx.type='IN' THEN tx.liters ELSE -tx.liters END),0) AS balance,
          MAX(tx.date) AS last_movement
        FROM trucks tr LEFT JOIN transactions tx ON tx.truck_id=tr.id
        GROUP BY tr.id,tr.emirate,tr.plate_code,tr.plate_number ORDER BY balance ASC
    """)
    today_summary = _read(conn, """
        SELECT COALESCE(SUM(CASE WHEN type='IN' THEN liters ELSE 0 END),0) AS total_in,
               COALESCE(SUM(CASE WHEN type='OUT' THEN liters ELSE 0 END),0) AS total_out,
               COUNT(*) AS movements
        FROM transactions WHERE date=%s
    """, [str(today)]).iloc[0]
    live_stock = float(balances["balance"].sum()) if not balances.empty else 0
    low_stock = balances[balances["balance"] <= minimum] if not balances.empty else balances
    pending = int(_read(conn, "SELECT COUNT(*) AS count FROM refill_requests WHERE status='PENDING'").iloc[0]["count"])

    st.markdown('<div class="section-label">TODAY AT A GLANCE</div>', unsafe_allow_html=True)
    metrics = st.columns(5)
    metric_data = [
        ("Live inventory", f"{live_stock:,.0f} L", f"Across {len(balances)} trucks"),
        ("Received today", f"{today_summary['total_in']:,.0f} L", "Fuel IN"),
        ("Delivered today", f"{today_summary['total_out']:,.0f} L", "Fuel OUT"),
        ("Movements today", f"{int(today_summary['movements']):,}", "Posted records"),
        ("Needs attention", f"{len(low_stock) + pending}", f"{len(low_stock)} stock · {pending} approvals"),
    ]
    for column, values in zip(metrics, metric_data):
        with column:
            stat_card(*values)

    st.write("")
    main, side = st.columns([2.05, 1], gap="large")
    with main:
        heading, button = st.columns([4, 1])
        heading.subheader("Live inventory")
        if button.button("View fleet", use_container_width=True):
            _go("Fleet Inventory")
        if balances.empty:
            st.info("No trucks have been registered yet.")
        else:
            view = balances.copy()
            view["status"] = view["balance"].apply(lambda value: "Low stock" if value <= minimum else "Available")
            view["share"] = view["balance"].clip(lower=0) / max(float(view["balance"].clip(lower=0).max()), 1)
            st.dataframe(
                view[["truck", "balance", "share", "last_movement", "status"]],
                use_container_width=True, hide_index=True, height=340,
                column_config={
                    "truck": st.column_config.TextColumn("Truck"),
                    "balance": st.column_config.NumberColumn("Current stock", format="%,.2f L"),
                    "share": st.column_config.ProgressColumn("Relative position", min_value=0, max_value=1),
                    "last_movement": st.column_config.TextColumn("Last movement"),
                    "status": st.column_config.TextColumn("Status"),
                },
            )

        st.subheader("30-day fuel movement")
        start = today - timedelta(days=29)
        trend = _read(conn, """
            SELECT date,
              SUM(CASE WHEN type='IN' THEN liters ELSE 0 END) AS received,
              SUM(CASE WHEN type='OUT' THEN liters ELSE 0 END) AS delivered
            FROM transactions WHERE date BETWEEN %s AND %s GROUP BY date ORDER BY date
        """, [str(start), str(today)])
        if trend.empty:
            st.info("No movements recorded during the last 30 days.")
        else:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=trend["date"], y=trend["received"], name="Received", mode="lines",
                                     line=dict(color=GREEN, width=3), fill="tozeroy", fillcolor="rgba(11,143,85,.08)"))
            fig.add_trace(go.Scatter(x=trend["date"], y=trend["delivered"], name="Delivered", mode="lines",
                                     line=dict(color=RED, width=3)))
            fig.update_layout(height=300, margin=dict(l=8,r=8,t=15,b=5), paper_bgcolor="white",
                              plot_bgcolor="white", legend=dict(orientation="h", y=1.1), hovermode="x unified")
            fig.update_xaxes(title="", showgrid=False)
            fig.update_yaxes(title="Litres", gridcolor="#EDF0F4")
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar":False})

    with side:
        st.subheader("Attention queue")
        if low_stock.empty and pending == 0:
            st.success("No urgent inventory actions are waiting.")
        else:
            if not low_stock.empty:
                for _, row in low_stock.head(5).iterrows():
                    st.markdown(f'<div class="queue-item critical"><div><b>{row["truck"]}</b><br>'
                                f'<span>{row["balance"]:,.0f} L remaining</span></div><strong>LOW</strong></div>',
                                unsafe_allow_html=True)
            if pending:
                st.markdown(f'<div class="queue-item warning"><div><b>Refill approvals</b><br>'
                            f'<span>{pending} request(s) waiting</span></div><strong>REVIEW</strong></div>',
                            unsafe_allow_html=True)
        a1, a2 = st.columns(2)
        if a1.button("Review stock", use_container_width=True):
            _go("Fleet Inventory")
        if a2.button("Approvals", use_container_width=True):
            _go("Approvals")

        st.subheader("Recent timeline")
        timeline = _read(conn, """
            SELECT timestamp, "user", action FROM audit_log ORDER BY id DESC LIMIT 8
        """)
        if timeline.empty:
            st.caption("No activity has been recorded.")
        else:
            for _, event in timeline.iterrows():
                stamp = pd.to_datetime(event["timestamp"]).strftime("%d %b · %H:%M")
                st.markdown(f'<div class="timeline-row"><div class="timeline-dot"></div><div>'
                            f'<b>{event["user"]}</b><span>{event["action"]}</span><small>{stamp}</small></div></div>',
                            unsafe_allow_html=True)
        if st.button("Open complete audit", use_container_width=True):
            _go("Audit Centre")

    st.caption(f"{company['application_name']} · Live operational view · Updated when this page refreshes")
