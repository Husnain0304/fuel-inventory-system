from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from ui import GREEN, RED, action_card, page_header, profile, stat_card


def _read(conn, query, params=None):
    return pd.read_sql_query(query, conn, params=params or [])


def _empty_chart(message):
    st.info(message)


def _open_page(label):
    st.session_state["main_navigation"] = label
    st.query_params["page"] = label
    st.rerun()


def render_dashboard(conn, truck_dict, truck_list):
    company = profile()
    page_header("Operations Command Centre", "Start daily work, monitor inventory and act on exceptions from one place.")

    st.markdown(f'<div class="eyebrow">{company["company_name"]} · Quick actions</div>', unsafe_allow_html=True)
    actions = st.columns(6)
    quick_actions = [
        ("Record movement", "Fuel Operations", "Uplift or delivery"),
        ("Transfer fuel", "Fuel Operations", "Safe truck transfer"),
        ("View stock", "Fleet Inventory", "Balances by truck"),
        ("Import data", "Integration Inbox", "Validate delivery file"),
        ("Generate report", "Report Centre", "Analyse and download"),
        ("Review audit", "Audit Centre", "Who changed what"),
    ]
    for column, (title, destination, note) in zip(actions, quick_actions):
        with column:
            action_card(title, note)
            if st.button("Open", key=f"quick_{destination}_{title}", use_container_width=True):
                _open_page(destination)

    st.write("")
    menu_columns = st.columns(4)
    menus = [
        ("Fuel operations", [("Transactions and transfers", "Fuel Operations"), ("Truck ledger", "Truck Ledger")]),
        ("Inventory control", [("Fleet inventory", "Fleet Inventory")]),
        ("Management", [("Approvals", "Approvals"), ("Reports", "Report Centre"), ("Audit", "Audit Centre")]),
        ("Data and setup", [("Integration inbox", "Integration Inbox"), ("Configuration", "Configuration")]),
    ]
    for index, (heading, links) in enumerate(menus):
        with menu_columns[index]:
            with st.popover(heading, use_container_width=True):
                for caption, destination in links:
                    if destination == "Configuration" and st.session_state.get("role") != "ADMIN":
                        continue
                    if st.button(caption, key=f"menu_{index}_{destination}", use_container_width=True):
                        _open_page(destination)

    controls = st.container(border=True)
    with controls:
        c1, c2, c3 = st.columns([1.2, 1.2, 2])
        start = c1.date_input("From", date.today() - timedelta(days=30), key="exec_start")
        end = c2.date_input("To", date.today(), key="exec_end")
        selected = c3.multiselect("Fleet scope", truck_list, placeholder="All trucks", key="exec_trucks")

    selected_ids = [truck_dict[name] for name in selected]
    scope_sql = ""
    params = [str(start), str(end)]
    if selected_ids:
        scope_sql = " AND tx.truck_id = ANY(%s)"
        params.append(selected_ids)

    summary = _read(
        conn,
        f"""
        SELECT
          COALESCE(SUM(CASE WHEN tx.type='IN' THEN tx.liters ELSE 0 END),0) AS total_in,
          COALESCE(SUM(CASE WHEN tx.type='OUT' THEN tx.liters ELSE 0 END),0) AS total_out,
          COUNT(*) AS transaction_count,
          COUNT(DISTINCT tx.truck_id) AS active_trucks
        FROM transactions tx
        WHERE tx.date BETWEEN %s AND %s {scope_sql}
        """,
        params,
    ).iloc[0]

    balance_params = []
    balance_scope = ""
    if selected_ids:
        balance_scope = " WHERE tx.truck_id = ANY(%s)"
        balance_params = [selected_ids]
    live_balance = _read(
        conn,
        f"""
        SELECT COALESCE(SUM(CASE WHEN tx.type='IN' THEN tx.liters ELSE -tx.liters END),0) AS balance
        FROM transactions tx {balance_scope}
        """,
        balance_params,
    ).iloc[0]["balance"]

    settings = _read(conn, "SELECT minimum_stock_level FROM settings ORDER BY id LIMIT 1")
    minimum_stock = float(settings.iloc[0]["minimum_stock_level"] or 0) if not settings.empty else 0

    cards = st.columns(4)
    with cards[0]:
        stat_card("Live fleet balance", f"{live_balance:,.0f} L", "Current inventory across selected fleet")
    with cards[1]:
        stat_card("Uplifted", f"{summary['total_in']:,.0f} L", f"{start:%d %b} – {end:%d %b}")
    with cards[2]:
        stat_card("Delivered", f"{summary['total_out']:,.0f} L", f"{int(summary['transaction_count']):,} recorded movements")
    with cards[3]:
        utilization = (summary["total_out"] / summary["total_in"] * 100) if summary["total_in"] else 0
        stat_card("Fuel utilization", f"{utilization:,.1f}%", "Delivered as a share of uplifted fuel")

    st.write("")
    trend, exceptions = st.columns([1.75, 1], gap="large")

    with trend:
        st.subheader("Fuel movement")
        daily = _read(
            conn,
            f"""
            SELECT tx.date,
              SUM(CASE WHEN tx.type='IN' THEN tx.liters ELSE 0 END) AS uplifted,
              SUM(CASE WHEN tx.type='OUT' THEN tx.liters ELSE 0 END) AS delivered
            FROM transactions tx
            WHERE tx.date BETWEEN %s AND %s {scope_sql}
            GROUP BY tx.date ORDER BY tx.date
            """,
            params,
        )
        if daily.empty:
            _empty_chart("No fuel movements in the selected period.")
        else:
            plot_df = daily.melt("date", value_vars=["uplifted", "delivered"], var_name="Movement", value_name="Liters")
            plot_df["Movement"] = plot_df["Movement"].str.title()
            fig = px.line(plot_df, x="date", y="Liters", color="Movement", markers=True,
                          color_discrete_map={"Uplifted": RED, "Delivered": "#171717"})
            fig.update_layout(height=330, margin=dict(l=10, r=10, t=15, b=10), legend_title_text="",
                              plot_bgcolor="white", paper_bgcolor="white", hovermode="x unified")
            fig.update_xaxes(title="", showgrid=False)
            fig.update_yaxes(title="Liters", gridcolor="#EEEAE7")
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    balances = _read(
        conn,
        """
        SELECT tr.id, CONCAT(tr.emirate,' ',tr.plate_code,' ',tr.plate_number) AS truck,
          COALESCE(SUM(CASE WHEN tx.type='IN' THEN tx.liters ELSE -tx.liters END),0) AS balance
        FROM trucks tr LEFT JOIN transactions tx ON tx.truck_id=tr.id
        GROUP BY tr.id, tr.emirate, tr.plate_code, tr.plate_number
        ORDER BY balance ASC
        """,
    )
    if selected_ids:
        balances = balances[balances["id"].isin(selected_ids)]
    low_stock = balances[balances["balance"] <= minimum_stock]

    with exceptions:
        st.subheader("Attention required")
        pending = _read(conn, "SELECT COUNT(*) AS count FROM refill_requests WHERE status='PENDING'").iloc[0]["count"]
        st.markdown(
            f'<div class="fillit-alert"><b>{len(low_stock)} low-stock trucks</b><br>'
            f'<span style="color:#777">At or below {minimum_stock:,.0f} L threshold</span></div>',
            unsafe_allow_html=True,
        )
        st.write("")
        st.markdown(
            f'<div class="fillit-alert"><b>{int(pending)} approvals pending</b><br>'
            '<span style="color:#777">Refill requests waiting for review</span></div>',
            unsafe_allow_html=True,
        )
        st.write("")
        if low_stock.empty:
            st.success("All selected trucks are above the minimum stock level.")
        else:
            st.dataframe(low_stock[["truck", "balance"]].head(8), use_container_width=True, hide_index=True,
                         column_config={"truck": "Truck", "balance": st.column_config.NumberColumn("Balance", format="%.0f L")})

    st.divider()
    inventory, activity = st.columns([1.35, 1], gap="large")

    with inventory:
        st.subheader("Fleet inventory position")
        view = balances.sort_values("balance", ascending=True).tail(12)
        if view.empty:
            _empty_chart("No registered trucks available.")
        else:
            colors = [RED if value <= minimum_stock else GREEN for value in view["balance"]]
            fig = go.Figure(go.Bar(x=view["balance"], y=view["truck"], orientation="h", marker_color=colors,
                                   text=[f"{v:,.0f} L" for v in view["balance"]], textposition="outside"))
            fig.update_layout(height=max(330, len(view) * 34), margin=dict(l=5, r=55, t=5, b=10),
                              plot_bgcolor="white", paper_bgcolor="white", xaxis_title="Liters")
            fig.update_xaxes(gridcolor="#EEEAE7")
            fig.update_yaxes(title="")
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    with activity:
        st.subheader("Latest activity")
        latest = _read(
            conn,
            'SELECT timestamp AS "Date & Time", "user" AS "User", action AS "Action" '
            "FROM audit_log ORDER BY id DESC LIMIT 12",
        )
        if latest.empty:
            st.info("No recorded activity yet.")
        else:
            st.dataframe(latest, use_container_width=True, hide_index=True, height=390)

    st.caption("FILLIT corporate fuel operations · Data refreshes when the page is opened or filters change.")
