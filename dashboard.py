from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ui import GREEN, RED, page_header, profile, stat_card
from rbac import allowed_pages


def _read(conn, query, params=None):
    return pd.read_sql_query(query, conn, params=params or [])

def _safe_read(conn,query,params=None):
    try: return _read(conn,query,params)
    except Exception:
        try: conn.rollback()
        except Exception: pass
        return pd.DataFrame()


def _go(label):
    st.session_state["navigation_target"] = label
    st.rerun()


def _launcher(title, description, destination, key, primary=False):
    st.markdown(
        f'<div class="workspace-card"><div class="workspace-icon">◇</div><div class="workspace-title">{title}</div>'
        f'<div class="workspace-copy">{description}</div></div>', unsafe_allow_html=True
    )
    if st.button("Open workspace", key=key, type="primary" if primary else "secondary", use_container_width=True):
        _go(destination)


def render_dashboard(conn, truck_dict, truck_list):
    company = profile()
    user = st.session_state.get("user", "User")
    permitted = allowed_pages(st.session_state.get("role", "VIEWER"))
    today = date.today()
    page_header("Command Centre", "Live inventory position, controlled workflows and management exceptions in one workspace.")

    hero_left, hero_right = st.columns([2.35, 1], gap="large")
    with hero_left:
        st.markdown(
            f'<div class="command-shell"><div class="hero-kicker">INVENTORY CONTROL ROOM</div>'
            f'<div class="hero-title">Good day, {user}. Your inventory network is ready.</div>'
            '<div class="hero-copy">Move from live stock to receiving, quality, reconciliation, valuation and assurance without losing operational context.</div>'
            '<div class="hero-meta"><span><b>CONTROLLED</b> transaction history</span><span><b>LIVE</b> exception monitoring</span><span><b>AUDITED</b> decisions</span></div>'
            '</div>',unsafe_allow_html=True
        )
    with hero_right:
        st.markdown(
            f'<div class="control-panel"><div class="control-label">ACTIVE CONTROL SESSION</div>'
            f'<div class="control-date">{today:%d %B %Y}</div><div class="control-copy">{company["company_name"]}<br>{company["application_name"]}<br><br>Signed in as <b>{user}</b></div>'
            '<div class="health-ring"><span style="width:100%"></span></div><div class="control-copy" style="margin-top:.55rem">Database connected · audit enabled</div></div>',unsafe_allow_html=True
        )

    st.markdown('<div class="section-label">WORKFLOW LAUNCHER</div>',unsafe_allow_html=True)
    launcher_groups={
        "Move inventory":["Fuel Operations","Storage Operations","Stock in Transit","Inventory Control"],
        "Manage supply":["Supplier Procurement","Receipt Costing","Supplier Master","Supplier Scorecards"],
        "Control quality":["Product & Quality","Batch Aging & FEFO","Measurement & Loss Control","Inventory Health"],
        "Analyse & assure":["Inventory Forecasting","Financial Valuation","Report Centre","Audit Centre"],
    }
    launch_columns=st.columns(4,gap="medium")
    for index,(group,options) in enumerate(launcher_groups.items()):
        with launch_columns[index]:
            visible_options=[option for option in options if option in permitted]
            if visible_options:
                selected_workspace=st.selectbox(group,visible_options,key=f"command_select_{index}")
                if st.button(f"Open {selected_workspace}",key=f"command_open_{index}",use_container_width=True,type="primary" if index==0 else "secondary"):
                    _go(selected_workspace)
            else:
                st.markdown(f"**{group}**"); st.caption("No workspace assigned to this role.")

    st.markdown('<div class="section-label">PRIORITY WORKSPACES</div>', unsafe_allow_html=True)
    actions = [
        ("Record movement", "Post a controlled truck receipt, issue or transfer.", "Fuel Operations", "launch_movement", True),
        ("Receive into storage", "Record supplier receipts, batches and variances.", "Storage Operations", "launch_storage_ops", False),
        ("Review exceptions", "Investigate balance, linkage, batch and control issues.", "Inventory Health", "launch_health", False),
        ("Approve decisions", "Review controlled requests waiting for authorization.", "Approvals", "launch_approvals", False),
        ("Reconcile stock", "Compare physical measurements with system quantities.", "Inventory Control", "launch_reconcile", False),
        ("Generate reports", "Create management-ready inventory information.", "Report Centre", "launch_reports", False),
    ]
    actions=[action for action in actions if action[2] in permitted]
    for start_index in range(0,len(actions),3):
        action_columns=st.columns(3,gap="medium")
        for column,details in zip(action_columns,actions[start_index:start_index+3]):
            with column: _launcher(*details)

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
    truck_stock = float(balances["balance"].sum()) if not balances.empty else 0
    tank_total=_safe_read(conn,"""SELECT COALESCE(SUM(balance),0) total FROM (SELECT tank_id,SUM(CASE WHEN type='IN' THEN liters ELSE -liters END) balance FROM tank_transactions WHERE COALESCE(record_status,'POSTED')='POSTED' GROUP BY tank_id) q""")
    tank_stock=float(tank_total.iloc[0,0] or 0) if not tank_total.empty else 0
    transit_total=_safe_read(conn,"SELECT COALESCE(SUM(dispatched_liters),0) total FROM inventory_transfers WHERE status='IN_TRANSIT'")
    in_transit=float(transit_total.iloc[0,0] or 0) if not transit_total.empty else 0
    live_stock=truck_stock+tank_stock+in_transit
    low_stock = balances[balances["balance"] <= minimum] if not balances.empty else balances
    pending = int(_read(conn, "SELECT COUNT(*) AS count FROM refill_requests WHERE status='PENDING'").iloc[0]["count"])
    tank_alerts=_safe_read(conn,"""SELECT CONCAT(d.code,' · ',t.code) AS asset,COALESCE(SUM(CASE WHEN x.type='IN' THEN x.liters ELSE -x.liters END),0) AS balance FROM storage_tanks t JOIN depots d ON d.id=t.depot_id LEFT JOIN tank_transactions x ON x.tank_id=t.id GROUP BY t.id,d.code HAVING COALESCE(SUM(CASE WHEN x.type='IN' THEN x.liters ELSE -x.liters END),0)<=t.minimum_stock_liters ORDER BY balance""")
    overdue=_safe_read(conn,"SELECT r.release_number FROM procurement_releases r WHERE r.status IN ('OPEN','PARTIALLY_RECEIVED') AND r.planned_delivery_date<CURRENT_DATE")
    upcoming=_safe_read(conn,"SELECT r.release_number FROM procurement_releases r WHERE r.status IN ('OPEN','PARTIALLY_RECEIVED') AND r.planned_delivery_date BETWEEN CURRENT_DATE AND CURRENT_DATE+7")
    claims=_safe_read(conn,"SELECT id FROM supplier_claims WHERE status NOT IN ('CLOSED','REJECTED')")
    reconciliations=_safe_read(conn,"SELECT id FROM stock_reconciliations WHERE status='PENDING'")
    unallocated=_safe_read(conn,"SELECT id FROM procurement_releases WHERE status IN ('OPEN','PARTIALLY_RECEIVED') AND destination_tank_id IS NULL")
    quality_hold=_safe_read(conn,"SELECT id FROM fuel_batches WHERE status='QUARANTINE'")
    expired_batches=_safe_read(conn,"SELECT id FROM fuel_batches WHERE status='RELEASED' AND expiry_date<CURRENT_DATE")
    calibration_due=_safe_read(conn,"SELECT id FROM tank_calibrations WHERE next_due_date<=CURRENT_DATE+30")
    open_incidents=_safe_read(conn,"SELECT id FROM inventory_incidents WHERE status='OPEN'")
    transit_overdue=_safe_read(conn,"SELECT id FROM inventory_transfers WHERE status='IN_TRANSIT' AND dispatched_at<CURRENT_TIMESTAMP-INTERVAL '24 hours'")
    total_attention=len(low_stock)+pending+len(tank_alerts)+len(overdue)+len(claims)+len(reconciliations)+len(unallocated)+len(quality_hold)+len(expired_batches)+len(calibration_due)+len(open_incidents)+len(transit_overdue)

    st.markdown('<div class="section-label">TODAY AT A GLANCE</div>', unsafe_allow_html=True)
    metrics = st.columns(5)
    metric_data = [
        ("Controlled inventory", f"{live_stock:,.0f} L", "Tanks, trucks and transit"),
        ("Tank inventory", f"{tank_stock:,.0f} L", "Storage position"),
        ("Truck inventory", f"{truck_stock:,.0f} L", f"Across {len(balances)} trucks"),
        ("In transit", f"{in_transit:,.0f} L", "Dispatched, not yet received"),
        ("Needs attention", f"{total_attention}", "Stock, releases, claims and controls"),
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
        if total_attention == 0:
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
            for _,row in tank_alerts.head(3).iterrows():
                st.markdown(f'<div class="queue-item critical"><div><b>{row["asset"]}</b><br><span>{row["balance"]:,.0f} L in storage</span></div><strong>TANK</strong></div>',unsafe_allow_html=True)
            if len(overdue): st.error(f"{len(overdue)} supplier release(s) overdue")
            if len(claims): st.warning(f"{len(claims)} supplier claim(s) need follow-up")
            if len(reconciliations): st.warning(f"{len(reconciliations)} reconciliation(s) pending")
            if len(unallocated): st.info(f"{len(unallocated)} incoming release(s) need a destination tank")
            if len(upcoming): st.info(f"{len(upcoming)} release(s) expected within 7 days")
            if len(expired_batches): st.error(f"{len(expired_batches)} expired batch(es) remain released")
            if len(quality_hold): st.warning(f"{len(quality_hold)} batch(es) in quarantine")
            if len(calibration_due): st.warning(f"{len(calibration_due)} tank calibration(s) due within 30 days")
            if len(open_incidents): st.warning(f"{len(open_incidents)} inventory incident(s) open")
            if len(transit_overdue): st.error(f"{len(transit_overdue)} transfer(s) in transit over 24 hours")
        a1, a2 = st.columns(2)
        if a1.button("Review stock", use_container_width=True):
            _go("Fleet Inventory")
        if a2.button("Approvals", use_container_width=True):
            _go("Approvals")
        b1,b2=st.columns(2)
        if b1.button("Procurement",use_container_width=True): _go("Supplier Procurement")
        if b2.button("Forecast",use_container_width=True): _go("Inventory Forecasting")

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
