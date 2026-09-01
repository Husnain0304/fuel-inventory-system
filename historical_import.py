from datetime import datetime
from io import BytesIO

import pandas as pd
import streamlit as st

from audit import record_event


BLOCKING={"INVALID","CONFLICT","AMBIGUOUS","FILE DUPLICATE","INSUFFICIENT STOCK","CLOSED PERIOD"}


def _ticket(value):
    if value is None or pd.isna(value): return ""
    text=str(value).strip()
    return "" if text.lower() in {"nan","none","null"} else text.upper()


def _template():
    sample=pd.DataFrame([
        {"date":"01-09-2026","truck":"DXB D 24631","liters":600.0,"ticket_number":"DEL-1001"},
        {"date":"01-09-2026","truck":"SHJ I 67814","liters":450.0,"ticket_number":"DEL-1002"},
    ])
    out=BytesIO()
    with pd.ExcelWriter(out,engine="openpyxl") as writer: sample.to_excel(writer,index=False,sheet_name="Outbound Deliveries")
    return out.getvalue()


def _standardize(uploaded):
    raw=pd.read_excel(uploaded)
    aliases={"ticket":"ticket_number","ticket_no":"ticket_number","ticketno":"ticket_number","plate":"truck","truck_number":"truck","quantity":"liters","qty":"liters","delivery_date":"date"}
    raw.columns=[aliases.get(str(c).strip().lower().replace(" ","_").replace(".",""),str(c).strip().lower().replace(" ","_").replace(".","")) for c in raw.columns]
    required={"date","truck","liters"}
    if not required.issubset(raw.columns): raise ValueError("The workbook must contain date, truck and liters columns.")
    if "ticket_number" not in raw.columns: raw["ticket_number"]=""
    return raw[["date","truck","liters","ticket_number"]].dropna(how="all").copy()


def _analyse(conn,source):
    trucks=pd.read_sql_query("""SELECT id,CONCAT(emirate,' ',plate_code,' ',plate_number) truck,operational_status,product_id FROM trucks""",conn)
    truck_map={str(r.truck).strip().upper():r for r in trucks.itertuples()}
    existing=pd.read_sql_query("""SELECT id,truck_id,date,liters,COALESCE(ticket_number,'') ticket_number FROM transactions WHERE type='OUT' AND COALESCE(record_status,'POSTED')='POSTED'""",conn)
    if not existing.empty:
        existing["day"]=pd.to_datetime(existing.date,errors="coerce").dt.date
        existing["ticket_norm"]=existing.ticket_number.map(_ticket)
    closed=pd.read_sql_query("SELECT start_date,end_date,period_name FROM inventory_periods WHERE status='CLOSED'",conn)
    balances=pd.read_sql_query("""SELECT tr.id,COALESCE(SUM(CASE WHEN tx.type='IN' THEN tx.liters ELSE -tx.liters END),0) balance FROM trucks tr LEFT JOIN transactions tx ON tx.truck_id=tr.id AND COALESCE(tx.record_status,'POSTED')='POSTED' GROUP BY tr.id""",conn)
    balance_map=dict(zip(balances.id,balances.balance))
    results=[]; file_keys=set(); file_tickets={}
    for index,row in source.reset_index(drop=True).iterrows():
        result={"row":index+2,"date":str(row.get("date","")),"truck":str(row.get("truck","")).strip().upper(),"liters":row.get("liters"),"ticket_number":_ticket(row.get("ticket_number")),"action":"","existing_id":None,"reason":""}
        try: result["parsed_date"]=pd.to_datetime(row.get("date"),dayfirst=True).date()
        except Exception: result.update(action="INVALID",reason="Date is missing or invalid; use DD-MM-YYYY"); results.append(result); continue
        profile=truck_map.get(result["truck"])
        if profile is None: result.update(action="INVALID",reason="Truck is not registered with this exact plate number"); results.append(result); continue
        result["truck_id"]=int(profile.id); result["product_id"]=profile.product_id
        try: result["liters"]=float(row.get("liters"))
        except Exception: result.update(action="INVALID",reason="Litres must be numeric"); results.append(result); continue
        if result["liters"]<=0: result.update(action="INVALID",reason="Litres must be greater than zero"); results.append(result); continue
        fallback=(result["truck_id"],result["parsed_date"],round(result["liters"],3))
        if fallback in file_keys or (result["ticket_number"] and result["ticket_number"] in file_tickets):
            result.update(action="FILE DUPLICATE",reason="The same delivery appears more than once in this workbook"); results.append(result); continue
        file_keys.add(fallback)
        if result["ticket_number"]: file_tickets[result["ticket_number"]]=index
        ticket_matches=existing[existing.ticket_norm.eq(result["ticket_number"])] if result["ticket_number"] and not existing.empty else existing.iloc[0:0]
        if len(ticket_matches):
            exact=ticket_matches[(ticket_matches.truck_id.eq(result["truck_id"]))&(ticket_matches.day.eq(result["parsed_date"]))&((ticket_matches.liters.astype(float)-result["liters"]).abs()<=.001)]
            if len(ticket_matches)==1 and len(exact)==1:
                result.update(action="MATCHED",existing_id=int(exact.iloc[0].id),reason="Ticket and inventory fields already match")
            else: result.update(action="CONFLICT",reason="Ticket number already exists with different or multiple inventory details")
            results.append(result); continue
        candidates=existing[(existing.truck_id.eq(result["truck_id"]))&(existing.day.eq(result["parsed_date"]))&((existing.liters.astype(float)-result["liters"]).abs()<=.001)] if not existing.empty else existing
        if len(candidates)==1:
            candidate=candidates.iloc[0]; existing_ticket=_ticket(candidate.ticket_number)
            if result["ticket_number"] and not existing_ticket: result.update(action="ENRICH",existing_id=int(candidate.id),reason="Existing delivery matched; missing ticket will be completed")
            elif not result["ticket_number"] or existing_ticket==result["ticket_number"]: result.update(action="MATCHED",existing_id=int(candidate.id),reason="Existing delivery matched by date, truck and litres")
            else: result.update(action="CONFLICT",existing_id=int(candidate.id),reason="Inventory fields match but ticket numbers conflict")
        elif len(candidates)>1: result.update(action="AMBIGUOUS",reason="Multiple existing deliveries match and no unique ticket identifies the record")
        elif str(profile.operational_status or "ACTIVE")!="ACTIVE": result.update(action="INVALID",reason=f"Truck status is {profile.operational_status}")
        else:
            closed_match=closed[(pd.to_datetime(closed.start_date).dt.date<=result["parsed_date"])&(pd.to_datetime(closed.end_date).dt.date>=result["parsed_date"])] if not closed.empty else closed
            if len(closed_match): result.update(action="CLOSED PERIOD",reason=f"Inventory period {closed_match.iloc[0].period_name} is closed")
            else: result.update(action="NEW",reason="No existing outbound delivery matches this row")
        results.append(result)
    result_frame=pd.DataFrame(results)
    if not result_frame.empty and "truck_id" in result_frame.columns:
        for truck_id,group in result_frame[result_frame.action.eq("NEW")].groupby("truck_id"):
            projected=float(balance_map.get(truck_id,0))-float(group.liters.sum())
            if projected<-.005:
                mask=result_frame.index.isin(group.index); result_frame.loc[mask,"action"]="INSUFFICIENT STOCK"; result_frame.loc[mask,"reason"]=f"Combined new rows would produce a projected balance of {projected:,.2f} L"
        result_frame["projected_effect"]=result_frame.apply(lambda r:-float(r.liters) if r.action=="NEW" else 0.0,axis=1)
    return result_frame


def _analysis_report(frame):
    export=frame.drop(columns=[c for c in ["parsed_date","truck_id","product_id"] if c in frame],errors="ignore").copy(); out=BytesIO()
    with pd.ExcelWriter(out,engine="openpyxl") as writer:
        export.to_excel(writer,index=False,sheet_name="Reconciliation Results")
        export.groupby("action",dropna=False).size().rename("rows").reset_index().to_excel(writer,index=False,sheet_name="Summary")
    return out.getvalue()


def _post(conn,analysis,file_name,user):
    if analysis.action.isin(BLOCKING).any(): raise ValueError("Resolve every invalid, conflicting, ambiguous, duplicate, insufficient-stock or closed-period row before posting.")
    cursor=conn.cursor()
    try:
        cursor.execute("INSERT INTO uploaded_files(file_name) VALUES (%s) ON CONFLICT(file_name) DO UPDATE SET uploaded_at=CURRENT_TIMESTAMP RETURNING id",(file_name,)); file_id=cursor.fetchone()[0]
        created=[]; enriched=[]
        for row in analysis.itertuples():
            if row.action=="ENRICH":
                cursor.execute("UPDATE transactions SET ticket_number=%s WHERE id=%s AND COALESCE(NULLIF(ticket_number,''),'')=''",(row.ticket_number,int(row.existing_id)))
                if cursor.rowcount: enriched.append(int(row.existing_id))
            elif row.action=="NEW":
                cursor.execute("""INSERT INTO transactions(truck_id,date,liters,type,ticket_number,file_id,created_by,product_id,movement_category,record_status)
                    VALUES (%s,%s,%s,'OUT',%s,%s,%s,%s,'BULK_DELIVERY','POSTED') RETURNING id""",(int(row.truck_id),str(row.parsed_date),float(row.liters),row.ticket_number or None,file_id,user,int(row.product_id) if pd.notna(row.product_id) else None)); created.append(cursor.fetchone()[0])
        cursor.execute('INSERT INTO audit_log("user",action,timestamp) VALUES (%s,%s,CURRENT_TIMESTAMP)',(user,f"Historical outbound reconciliation {file_name}: {len(created)} created, {len(enriched)} enriched, {int(analysis.action.eq('MATCHED').sum())} matched")); conn.commit()
        record_event(conn,"POST_HISTORICAL_OUTBOUND_IMPORT","Integration Inbox","Uploaded File",file_id,f"{len(created)} new OUT; {len(enriched)} tickets enriched; {int(analysis.action.eq('MATCHED').sum())} existing matches")
        return len(created),len(enriched)
    except Exception: conn.rollback(); raise


def render_historical_import(conn):
    user=st.session_state.get("user","System")
    if "historical_import_analysis" not in st.session_state: st.session_state.historical_import_analysis=None
    if "historical_import_name" not in st.session_state: st.session_state.historical_import_name=""
    mode=st.radio("Integration workspace",["Upload & reconcile","Import batches","Transaction lookup"],horizontal=True,label_visibility="collapsed")
    if mode=="Upload & reconcile":
        a,b=st.columns([3,1]); a.markdown("### Historical outbound reconciliation"); b.download_button("Download Excel template",_template(),"outbound_delivery_template.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",use_container_width=True)
        st.caption("Upload old and new deliveries together. Nothing changes until analysis is clean and you explicitly post it.")
        uploaded=st.file_uploader("Outbound delivery workbook",type=["xlsx"])
        if uploaded is not None:
            try:
                if st.session_state.historical_import_name and st.session_state.historical_import_name!=uploaded.name:
                    st.session_state.historical_import_analysis=None; st.session_state.historical_import_name=""
                source=_standardize(uploaded); st.dataframe(source,use_container_width=True,hide_index=True,height=260)
                if st.button("Analyse and reconcile workbook",type="primary",use_container_width=True):
                    st.session_state.historical_import_analysis=_analyse(conn,source); st.session_state.historical_import_name=uploaded.name; st.rerun()
            except Exception as error: st.error(str(error))
        analysis=st.session_state.historical_import_analysis
        if analysis is not None:
            st.divider(); st.subheader("Reconciliation result")
            counts=analysis.action.value_counts(); columns=st.columns(5)
            for column,(label,key) in zip(columns,[("New","NEW"),("Matched","MATCHED"),("Enriched","ENRICH"),("Blocked","BLOCKED"),("Rows","ALL")]):
                value=len(analysis) if key=="ALL" else (int(analysis.action.isin(BLOCKING).sum()) if key=="BLOCKED" else int(counts.get(key,0))); column.metric(label,value)
            display=analysis.drop(columns=[c for c in ["parsed_date","truck_id","product_id"] if c in analysis],errors="ignore")
            st.dataframe(display,use_container_width=True,hide_index=True,height=390,column_config={"action":st.column_config.TextColumn("Decision"),"projected_effect":st.column_config.NumberColumn("Inventory effect",format="%,.2f L")})
            st.download_button("Download reconciliation report",_analysis_report(analysis),f"reconciliation_{datetime.now():%Y%m%d_%H%M%S}.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            blocked=analysis.action.isin(BLOCKING).any(); confirm=st.checkbox("I confirm the reconciliation result and authorize the safe rows to be posted.",disabled=blocked)
            if blocked: st.error("Posting is blocked. Correct or remove every red/blocked row in the source workbook and analyse it again.")
            if st.button("Post reconciled outbound deliveries",type="primary",use_container_width=True,disabled=blocked or not confirm):
                try:
                    created,enriched=_post(conn,analysis,st.session_state.historical_import_name,user); st.success(f"Completed: {created} new outbound transactions posted and {enriched} existing ticket numbers completed."); st.session_state.historical_import_analysis=None; st.session_state.historical_import_name=""
                except Exception as error: st.error(str(error))
    elif mode=="Import batches":
        batches=pd.read_sql_query("""SELECT f.id,f.file_name,f.uploaded_at,COUNT(t.id) transactions,COALESCE(SUM(t.liters),0) liters FROM uploaded_files f LEFT JOIN transactions t ON t.file_id=f.id GROUP BY f.id ORDER BY f.uploaded_at DESC""",conn)
        st.dataframe(batches,use_container_width=True,hide_index=True,height=500)
    else:
        search=st.text_input("Search truck, ticket or transaction ID")
        history=pd.read_sql_query("""SELECT tx.id,tx.date,CONCAT(tr.emirate,' ',tr.plate_code,' ',tr.plate_number) truck,tx.liters,tx.ticket_number,tx.created_by,tx.file_id FROM transactions tx JOIN trucks tr ON tr.id=tx.truck_id WHERE tx.type='OUT' ORDER BY tx.id DESC LIMIT 2000""",conn)
        if search:
            combined=history.astype(str).agg(" ".join,axis=1); history=history[combined.str.contains(search,case=False,na=False,regex=False)]
        st.dataframe(history,use_container_width=True,hide_index=True,height=520)
