import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, date, timedelta

def render_dashboard(conn, truck_dict, truck_list):
    st.title("⛽ FILLIT DIESEL — OPERATIONAL COMMAND CENTER")
    st.caption("Live Fleet Inventory, Predictive Analytics & Demand Intelligence")
    st.markdown("---")

    # ==========================================
    # 1. LIVE SYSTEM FUEL BALANCE & METRIC CARDS
    # ==========================================
    live_inventory_query = """
        SELECT 
            CONCAT(trucks.emirate, ' ', trucks.plate_code, ' ', trucks.plate_number) AS truck,
            SUM(CASE WHEN type='IN' THEN liters ELSE 0 END) -
            SUM(CASE WHEN type='OUT' THEN liters ELSE 0 END) AS current_balance
        FROM transactions
        JOIN trucks ON transactions.truck_id = trucks.id
        GROUP BY trucks.id, trucks.emirate, trucks.plate_code, trucks.plate_number
        ORDER BY current_balance DESC
    """
    inventory_df = pd.read_sql_query(live_inventory_query, conn)
    total_current_inventory = inventory_df["current_balance"].sum() if not inventory_df.empty else 0.0

    # Historical Daily Outflow (Last 30 Days)
    thirty_days_ago = (date.today() - timedelta(days=30)).strftime("%Y-%m-%d")
    outflow_query = """
        SELECT date, SUM(liters) as daily_out
        FROM transactions
        WHERE type = 'OUT' AND date >= %s
        GROUP BY date
    """
    outflow_df = pd.read_sql_query(outflow_query, conn, params=[thirty_days_ago])

    if not outflow_df.empty:
        total_30d_out = outflow_df["daily_out"].sum()
        active_days = len(outflow_df["date"].unique())
        avg_daily_consumption = total_30d_out / max(active_days, 1)
    else:
        avg_daily_consumption = 0.0

    # Upper Visual Layout: Gauge Needle + Fleet Breakdown Chart
    col_gauge, col_pie = st.columns([2, 3])

    with col_gauge:
        st.subheader("🎯 System Fuel Capacity Gauge")
        
        # Max capacity target dynamic scaling (assumes minimum 50k L gauge scale)
        max_capacity_target = max(50000.0, total_current_inventory * 1.3)
        
        # Custom Plotly Gauge Needle Meter
        fig_gauge = go.Figure(go.Indicator(
            mode="gauge+number+delta",
            value=total_current_inventory,
            domain={'x': [0, 1], 'y': [0, 1]},
            title={'text': "Total Diesel Stock (Liters)", 'font': {'size': 18, 'color': "#0F172A"}},
            number={'suffix': " L", 'font': {'size': 26, 'color': "#1E293B"}},
            gauge={
                'axis': {'range': [0, max_capacity_target], 'tickwidth': 1, 'tickcolor': "#475569"},
                'bar': {'color': "#0284C7"},
                'bgcolor': "white",
                'borderwidth': 2,
                'bordercolor': "#E2E8F0",
                'steps': [
                    {'range': [0, max_capacity_target * 0.25], 'color': '#FECACA'},
                    {'range': [max_capacity_target * 0.25, max_capacity_target * 0.60], 'color': '#FEF08A'},
                    {'range': [max_capacity_target * 0.60, max_capacity_target], 'color': '#BBF7D0'}
                ],
                'threshold': {
                    'line': {'color': "#DC2626", 'width': 4},
                    'thickness': 0.75,
                    'value': total_current_inventory
                }
            }
        ))
        fig_gauge.update_layout(height=280, margin=dict(l=20, r=20, t=40, b=20))
        st.plotly_chart(fig_gauge, use_container_width=True)

    with col_pie:
        st.subheader("🚛 Live Fleet Stock Distribution")
        if not inventory_df.empty:
            fig_donut = px.pie(
                inventory_df, 
                names="truck", 
                values="current_balance", 
                hole=0.5,
                color_discrete_sequence=px.colors.qualitative.Prism
            )
            fig_donut.update_traces(textinfo="label+value", texttemplate="%{label}:<br>%{value:,.0f} L")
            fig_donut.update_layout(height=280, margin=dict(l=10, r=10, t=30, b=10), showlegend=False)
            st.plotly_chart(fig_donut, use_container_width=True)
        else:
            st.info("No active fleet balances registered.")

    st.markdown("---")

    # ==========================================
    # 2. AD-HOC DEMAND & PREDICTIVE FORECASTING
    # ==========================================
    st.subheader("🔮 Predictive Stock & Ad-Hoc Demand Simulator")

    with st.expander("➕ Inject Ad-Hoc / New Customer Expected Bulk Orders", expanded=True):
        st.caption("Simulate impact on inventory reserves by specifying expected order volume and requested date.")
        col_ad1, col_ad2, col_ad3 = st.columns([2, 2, 3])
        future_date = col_ad1.date_input("Target Delivery Date", value=date.today() + timedelta(days=1))
        ad_hoc_liters = col_ad2.number_input("Ad-Hoc Order Volume (Liters)", min_value=0.0, step=500.0)
        demand_notes = col_ad3.text_input("Customer / Project Reference", placeholder="e.g. Ad-hoc Construction Site Fleet")

    effective_stock = total_current_inventory - ad_hoc_liters

    if avg_daily_consumption > 0:
        days_until_depletion = effective_stock / avg_daily_consumption
        estimated_depletion_date = date.today() + timedelta(days=max(0, int(days_until_depletion)))
    else:
        days_until_depletion = 0
        estimated_depletion_date = "N/A"

    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    col_m1.metric("30-Day Avg Outflow", f"{avg_daily_consumption:,.2f} L/day")
    col_m2.metric("Ad-Hoc Demand Applied", f"{ad_hoc_liters:,.2f} L")
    col_m3.metric("Adjusted Stock Reserve", f"{effective_stock:,.2f} L")
    
    if isinstance(estimated_depletion_date, date):
        col_m4.metric("Est. Depletion Date", estimated_depletion_date.strftime("%Y-%m-%d"))
    else:
        col_m4.metric("Est. Depletion Date", estimated_depletion_date)

    # VISUAL FORECAST CHART
    st.markdown("#### 📈 Interactive Calendar Lookahead Projection")
    target_forecast_date = st.date_input("Select Calendar Horizon Date", value=date.today() + timedelta(days=14))

    days_ahead = (target_forecast_date - date.today()).days

    if days_ahead > 0:
        forecast_dates = [date.today() + timedelta(days=i) for i in range(days_ahead + 1)]
        projected_stock_levels = []
        
        current_calc_stock = total_current_inventory
        for d in forecast_dates:
            if d == future_date:
                current_calc_stock -= ad_hoc_liters
            current_calc_stock -= avg_daily_consumption
            projected_stock_levels.append(max(0.0, current_calc_stock))

        forecast_chart_df = pd.DataFrame({
            "Date": forecast_dates,
            "Projected Remaining Stock (L)": projected_stock_levels
        })

        fig_line = px.area(
            forecast_chart_df, 
            x="Date", 
            y="Projected Remaining Stock (L)",
            title=f"Stock Depletion Forecast path through {target_forecast_date.strftime('%Y-%m-%d')}",
            color_discrete_sequence=["#0284C7"]
        )
        fig_line.add_hline(y=0, line_dash="dash", line_color="red", annotation_text="Stock Depleted")
        fig_line.update_layout(height=320, margin=dict(l=20, r=20, t=40, b=20))
        st.plotly_chart(fig_line, use_container_width=True)

        final_projected_stock = projected_stock_levels[-1]
        if final_projected_stock <= 0:
            st.warning(f"⚠️ **Stock Alert:** Current reserves and projected consumption indicate fuel depletion before {target_forecast_date.strftime('%Y-%m-%d')}. Additional uplift required!")
        else:
            st.success(f"✅ **Stock Safe:** Expected inventory reserve on {target_forecast_date.strftime('%Y-%m-%d')} will be approximately **{final_projected_stock:,.2f} L**.")
    else:
        st.caption("Select a future date above to render the projected inventory area chart.")

    st.markdown("---")

    # ==========================================
    # 3. DATE-WISE & TRUCK-WISE OPERATIONS
    # ==========================================
    st.subheader("📊 Operational Fuel Movements & Truck Breakdown")

    col_f1, col_f2, col_f3 = st.columns([2, 2, 3])
    from_date = col_f1.date_input("From Date", value=date.today() - timedelta(days=7))
    to_date = col_f2.date_input("To Date", value=date.today())
    selected_trucks = col_f3.multiselect("Filter Trucks (Leave blank for All)", truck_list)

    params = [str(from_date), str(to_date)]

    if selected_trucks:
        truck_ids = [truck_dict[t] for t in selected_trucks]
        placeholders = ",".join(["%s"] * len(truck_ids))
        truck_filter_sql = f" AND transactions.truck_id IN ({placeholders}) "
        params.extend(truck_ids)
    else:
        truck_filter_sql = ""

    tx_query = f"""
        SELECT 
            transactions.date,
            CONCAT(trucks.emirate, ' ', trucks.plate_code, ' ', trucks.plate_number) AS truck,
            transactions.type,
            transactions.liters
        FROM transactions
        JOIN trucks ON transactions.truck_id = trucks.id
        WHERE transactions.date BETWEEN %s AND %s {truck_filter_sql}
        ORDER BY transactions.date DESC
    """
    
    tx_df = pd.read_sql_query(tx_query, conn, params=params)

    tab_uplift, tab_delivery = st.tabs(["📥 Uplift Intelligence (IN)", "📤 Delivery Intelligence (OUT)"])

    with tab_uplift:
        uplift_df = tx_df[tx_df["type"] == "IN"]
        if not uplift_df.empty:
            grouped_up = uplift_df.groupby(["date", "truck"])["liters"].sum().reset_index().rename(columns={"liters": "Uplifted Liters"})
            
            # Interactive Bar Chart for Uplifts
            fig_up = px.bar(
                grouped_up, 
                x="date", 
                y="Uplifted Liters", 
                color="truck", 
                title="Date-Wise Fuel Uplifts by Truck",
                barmode="stack",
                color_discrete_sequence=px.colors.qualitative.Bold
            )
            fig_up.update_layout(height=320, margin=dict(l=20, r=20, t=40, b=20))
            st.plotly_chart(fig_up, use_container_width=True)
            
            st.dataframe(grouped_up, use_container_width=True, hide_index=True)
        else:
            st.info("No uplift entries found for the selected parameters.")

    with tab_delivery:
        delivery_df = tx_df[tx_df["type"] == "OUT"]
        if not delivery_df.empty:
            grouped_del = delivery_df.groupby(["date", "truck"])["liters"].sum().reset_index().rename(columns={"liters": "Delivered Liters"})
            
            # Interactive Bar Chart for Deliveries
            fig_del = px.bar(
                grouped_del, 
                x="date", 
                y="Delivered Liters", 
                color="truck", 
                title="Date-Wise Fuel Deliveries by Truck",
                barmode="stack",
                color_discrete_sequence=px.colors.qualitative.Safe
            )
            fig_del.update_layout(height=320, margin=dict(l=20, r=20, t=40, b=20))
            st.plotly_chart(fig_del, use_container_width=True)

            st.dataframe(grouped_del, use_container_width=True, hide_index=True)
        else:
            st.info("No delivery entries found for the selected parameters.")
