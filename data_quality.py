from io import BytesIO
import hashlib

import pandas as pd
import streamlit as st
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from audit import record_event
from rbac import can
from ui import page_header


ISSUE_PAGES = {
    "DUPLICATE_TICKET": "Transaction Control", "MISSING_TICKET": "Transaction Control",
    "NEGATIVE_INVENTORY": "Inventory Control", "CLOSED_PERIOD_TRANSACTION": "Transaction Control",
    "ORPHAN_TRANSFER": "Transaction Control", "UNLINKED_RECEIPT": "Product & Quality",
    "INCOMPLETE_TRUCK": "Fleet Inventory",
}


def ensure_data_quality_schema(conn):
    cursor=conn.cursor()
    try:
        cursor.execute("""CREATE TABLE IF NOT EXISTS data_quality_issues(
            id BIGSERIAL PRIMARY KEY,fingerprint TEXT NOT NULL UNIQUE,issue_type TEXT NOT NULL,
            severity TEXT NOT NULL CHECK(severity IN ('CRITICAL','WARNING','INFORMATION')),
            title TEXT NOT NULL,description TEXT NOT NULL,entity_type TEXT,entity_id TEXT,
            target_page TEXT,status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','RESOLVED','ACCEPTED')),
            assigned_to TEXT,first_detected_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_detected_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,resolved_at TIMESTAMPTZ,
            resolved_by TEXT,resolution_note TEXT)""")
        cursor.execute("""CREATE TABLE IF NOT EXISTS data_quality_runs(
            id BIGSERIAL PRIMARY KEY,run_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            run_by TEXT,issues_detected INTEGER NOT NULL DEFAULT 0,critical_count INTEGER NOT NULL DEFAULT 0,
            warning_count INTEGER NOT NULL DEFAULT 0,quality_score REAL NOT NULL DEFAULT 100)""")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_quality_issues_status ON data_quality_issues(status,severity,last_detected_at DESC)")
        conn.commit()
    except Exception: conn.rollback(); raise


def _fingerprint(issue_type,entity_type,entity_id):
    return hashlib.sha256(f"{issue_type}|{entity_type}|{entity_id}".encode()).hexdigest()


def _discover(conn):
    issues=[]
    def add(kind,severity,title,description,entity_type,entity_id):
        issues.append({"fingerprint":_fingerprint(kind,entity_type,entity_id),"issue_type":kind,"severity":severity,
            "title":title,"description":description,"entity_type":entity_type,"entity_id":str(entity_id),"target_page":ISSUE_PAGES[kind]})

    duplicate=pd.read_sql_query("""SELECT UPPER(TRIM(ticket_number)) ticket,COUNT(*) total,STRING_AGG(id::text,', ' ORDER BY id) transaction_ids
        FROM transactions WHERE COALESCE(record_status,'POSTED')='POSTED' AND NULLIF(TRIM(ticket_number),'') IS NOT NULL
        GROUP BY UPPER(TRIM(ticket_number)) HAVING COUNT(*)>1""",conn)
    for row in duplicate.itertuples(): add("DUPLICATE_TICKET","CRITICAL",f"Duplicate ticket {row.ticket}",f"Ticket is used by {row.total} transactions: {row.transaction_ids}.","TICKET",row.ticket)

    missing=pd.read_sql_query("""SELECT id,date,truck_id,liters,type FROM transactions WHERE COALESCE(record_status,'POSTED')='POSTED'
        AND COALESCE(movement_category,'STANDARD') NOT IN ('TRANSFER','TRANSFER_IN','TRANSFER_OUT') AND NULLIF(TRIM(ticket_number),'') IS NULL""",conn)
    for row in missing.itertuples(): add("MISSING_TICKET","WARNING",f"TX-{row.id} has no ticket/reference",f"{row.type} movement of {float(row.liters):,.2f} L dated {row.date} requires a supporting reference.","TRANSACTION",row.id)

    negative=pd.read_sql_query("""SELECT tr.id,CONCAT(tr.emirate,' ',tr.plate_code,' ',tr.plate_number) truck,
        COALESCE(SUM(CASE WHEN tx.type='IN' THEN tx.liters ELSE -tx.liters END),0) balance
        FROM trucks tr LEFT JOIN transactions tx ON tx.truck_id=tr.id AND COALESCE(tx.record_status,'POSTED')='POSTED'
        GROUP BY tr.id HAVING COALESCE(SUM(CASE WHEN tx.type='IN' THEN tx.liters ELSE -tx.liters END),0)<-0.005""",conn)
    for row in negative.itertuples(): add("NEGATIVE_INVENTORY","CRITICAL",f"Negative inventory · {row.truck}",f"Calculated balance is {float(row.balance):,.2f} L.","TRUCK",row.id)

    closed=pd.read_sql_query("""SELECT tx.id,tx.date,p.period_name FROM transactions tx JOIN inventory_periods p
        ON tx.date BETWEEN p.start_date AND p.end_date WHERE p.status='CLOSED' AND tx.created_at>p.closed_at
        AND COALESCE(tx.record_status,'POSTED')='POSTED'""",conn)
    for row in closed.itertuples(): add("CLOSED_PERIOD_TRANSACTION","CRITICAL",f"TX-{row.id} posted after period close",f"Transaction date {row.date} belongs to closed period {row.period_name}.","TRANSACTION",row.id)

    transfers=pd.read_sql_query("""SELECT tx.id,tx.transfer_partner_id FROM transactions tx LEFT JOIN transactions partner ON partner.id=tx.transfer_partner_id
        WHERE tx.movement_category LIKE 'TRANSFER%' AND (tx.transfer_partner_id IS NULL OR partner.id IS NULL)""",conn)
    for row in transfers.itertuples(): add("ORPHAN_TRANSFER","CRITICAL",f"Incomplete transfer · TX-{row.id}","The linked transfer partner is missing.","TRANSACTION",row.id)

    receipts=pd.read_sql_query("""SELECT id,reference,COALESCE(accepted_liters,liters) liters FROM tank_transactions
        WHERE movement_category='SUPPLIER_RECEIPT' AND batch_id IS NULL""",conn)
    for row in receipts.itertuples(): add("UNLINKED_RECEIPT","WARNING",f"STX-{row.id} is not linked to a batch",f"Supplier receipt {row.reference or 'without reference'} for {float(row.liters):,.2f} L has no quality batch.","TANK_TRANSACTION",row.id)

    trucks=pd.read_sql_query("""SELECT id,emirate,plate_code,plate_number,capacity_liters,product_id FROM trucks
        WHERE NULLIF(TRIM(emirate),'') IS NULL OR NULLIF(TRIM(plate_code),'') IS NULL OR NULLIF(TRIM(plate_number),'') IS NULL
        OR COALESCE(capacity_liters,0)<=0 OR product_id IS NULL""",conn)
    for row in trucks.itertuples(): add("INCOMPLETE_TRUCK","WARNING",f"Truck record {row.id} is incomplete","Plate identity, capacity and assigned product are required.","TRUCK",row.id)
    return issues


def run_data_quality_scan(conn,run_by="System"):
    ensure_data_quality_schema(conn); discovered=_discover(conn); fingerprints={item["fingerprint"] for item in discovered}; cursor=conn.cursor()
    try:
        for item in discovered:
            cursor.execute("""INSERT INTO data_quality_issues(fingerprint,issue_type,severity,title,description,entity_type,entity_id,target_page)
                VALUES(%(fingerprint)s,%(issue_type)s,%(severity)s,%(title)s,%(description)s,%(entity_type)s,%(entity_id)s,%(target_page)s)
                ON CONFLICT(fingerprint) DO UPDATE SET severity=EXCLUDED.severity,title=EXCLUDED.title,description=EXCLUDED.description,
                target_page=EXCLUDED.target_page,last_detected_at=CURRENT_TIMESTAMP,
                status=CASE WHEN data_quality_issues.status='ACCEPTED' THEN 'ACCEPTED' ELSE 'OPEN' END,
                resolved_at=CASE WHEN data_quality_issues.status='ACCEPTED' THEN data_quality_issues.resolved_at ELSE NULL END,
                resolved_by=CASE WHEN data_quality_issues.status='ACCEPTED' THEN data_quality_issues.resolved_by ELSE NULL END""",item)
        if fingerprints:
            cursor.execute("""UPDATE data_quality_issues SET status='RESOLVED',resolved_at=CURRENT_TIMESTAMP,resolved_by='System',
                resolution_note='Automatically cleared by the latest data-quality scan.' WHERE status='OPEN' AND NOT (fingerprint=ANY(%s))""",(list(fingerprints),))
        else:
            cursor.execute("UPDATE data_quality_issues SET status='RESOLVED',resolved_at=CURRENT_TIMESTAMP,resolved_by='System',resolution_note='Automatically cleared by the latest data-quality scan.' WHERE status='OPEN'")
        critical=sum(i["severity"]=="CRITICAL" for i in discovered); warning=sum(i["severity"]=="WARNING" for i in discovered)
        score=max(0,100-critical*8-warning*3)
        cursor.execute("INSERT INTO data_quality_runs(run_by,issues_detected,critical_count,warning_count,quality_score) VALUES(%s,%s,%s,%s,%s)",(run_by,len(discovered),critical,warning,score)); conn.commit()
        return len(discovered),score
    except Exception: conn.rollback(); raise


def run_daily_data_quality_scan(conn):
    ensure_data_quality_schema(conn); cursor=conn.cursor(); cursor.execute("SELECT MAX(run_at)::date FROM data_quality_runs"); last=cursor.fetchone()[0]
    if last is None or last < pd.Timestamp.now().date(): run_data_quality_scan(conn,"Automatic daily control")


def _report(issues,runs,company):
    wb=Workbook(); wb.remove(wb.active)
    summary=pd.DataFrame({"Control":["Company","Generated","Open issues","Critical","Warnings","Quality score"],"Value":[company,pd.Timestamp.now().strftime("%d %b %Y %H:%M"),len(issues),int(issues.severity.eq("CRITICAL").sum()) if not issues.empty else 0,int(issues.severity.eq("WARNING").sum()) if not issues.empty else 0,float(runs.iloc[0].quality_score) if not runs.empty else 100]})
    for name,data in {"Executive Summary":summary,"Issue Register":issues,"Scan History":runs}.items():
        ws=wb.create_sheet(name); clean=data.copy(); ws.append(list(clean.columns))
        for row in clean.where(pd.notna(clean),None).itertuples(index=False,name=None): ws.append([str(v) if isinstance(v,pd.Timestamp) else v for v in row])
        for cell in ws[1]: cell.fill=PatternFill("solid",fgColor="172033"); cell.font=Font(color="FFFFFF",bold=True); cell.alignment=Alignment(wrap_text=True)
        ws.freeze_panes="A2"; ws.auto_filter.ref=ws.dimensions
        for column in ws.columns: ws.column_dimensions[column[0].column_letter].width=min(max(13,max(len(str(c.value or "")) for c in column)+2),40)
    wb["Executive Summary"]["A1"].fill=PatternFill("solid",fgColor="9E1B1B")
    out=BytesIO(); wb.save(out); return out.getvalue()


def render_data_quality(conn):
    ensure_data_quality_schema(conn); user=st.session_state.get("user","System")
    page_header("Inventory Data Quality","Detect, assign and resolve records that could weaken inventory accuracy or financial control.")
    issues=pd.read_sql_query("SELECT * FROM data_quality_issues ORDER BY CASE severity WHEN 'CRITICAL' THEN 1 WHEN 'WARNING' THEN 2 ELSE 3 END,last_detected_at DESC",conn)
    runs=pd.read_sql_query("SELECT * FROM data_quality_runs ORDER BY id DESC LIMIT 100",conn)
    open_issues=issues[issues.status.eq("OPEN")] if not issues.empty else issues
    score=float(runs.iloc[0].quality_score) if not runs.empty else 100
    a,b,c,d=st.columns(4); a.metric("Quality score",f"{score:.0f}/100"); b.metric("Open issues",len(open_issues)); c.metric("Critical",int(open_issues.severity.eq("CRITICAL").sum()) if not open_issues.empty else 0); d.metric("Warnings",int(open_issues.severity.eq("WARNING").sum()) if not open_issues.empty else 0)
    if st.button("Run data-quality scan now",type="primary",use_container_width=True):
        total,new_score=run_data_quality_scan(conn,user); record_event(conn,"RUN_DATA_QUALITY_SCAN","Data Quality","Control Run",None,f"Detected {total} issues; score {new_score}"); st.rerun()
    register,manage,history,report=st.tabs(["Issue register","Resolve & assign","Scan history","Management report"])
    with register:
        f1,f2,f3=st.columns(3); status=f1.multiselect("Status",["OPEN","RESOLVED","ACCEPTED"],default=["OPEN"]); severity=f2.multiselect("Severity",["CRITICAL","WARNING","INFORMATION"],default=["CRITICAL","WARNING","INFORMATION"]); kind=f3.multiselect("Issue type",sorted(issues.issue_type.unique()) if not issues.empty else [])
        view=issues[issues.status.isin(status)&issues.severity.isin(severity)] if not issues.empty else issues
        if kind: view=view[view.issue_type.isin(kind)]
        st.dataframe(view[["id","severity","issue_type","title","description","entity_type","entity_id","status","assigned_to","last_detected_at"]],use_container_width=True,hide_index=True,height=480)
    with manage:
        if issues.empty: st.success("No data-quality issues have been detected.")
        else:
            labels={f"DQ-{int(r.id)} · {r.severity} · {r.title}":r for r in issues.itertuples()}; selected=labels[st.selectbox("Select issue",list(labels))]
            st.markdown(f"### {selected.title}"); st.write(selected.description); st.caption(f"{selected.entity_type} {selected.entity_id} · Last detected {pd.to_datetime(selected.last_detected_at):%d %b %Y %H:%M}")
            left,right=st.columns(2)
            if left.button("Open fixing workspace",type="primary",use_container_width=True): st.session_state["navigation_target"]=selected.target_page; st.rerun()
            assignee=right.text_input("Assign to",value=selected.assigned_to or "",placeholder="Username")
            note=st.text_area("Resolution / acceptance note")
            action=st.radio("Update status",["OPEN","RESOLVED","ACCEPTED"],index=["OPEN","RESOLVED","ACCEPTED"].index(selected.status),horizontal=True)
            if st.button("Save issue update",use_container_width=True):
                if action in ("RESOLVED","ACCEPTED") and len(note.strip())<5: st.error("Enter a clear resolution or acceptance note.")
                else:
                    cursor=conn.cursor(); cursor.execute("""UPDATE data_quality_issues SET status=%s,assigned_to=%s,resolution_note=%s,
                        resolved_at=CASE WHEN %s='OPEN' THEN NULL ELSE CURRENT_TIMESTAMP END,resolved_by=CASE WHEN %s='OPEN' THEN NULL ELSE %s END WHERE id=%s""",(action,assignee.strip() or None,note.strip() or None,action,action,user,int(selected.id))); conn.commit()
                    record_event(conn,"UPDATE_DATA_QUALITY_ISSUE","Data Quality","Data Quality Issue",selected.id,f"Status {action}; assigned to {assignee or 'unassigned'}"); st.rerun()
    with history: st.dataframe(runs,use_container_width=True,hide_index=True,height=460)
    with report:
        company=st.session_state.get("company_profile",{}).get("company_name","Company")
        st.download_button("Download data-quality management report",_report(issues,runs,company),f"data_quality_{pd.Timestamp.now():%Y%m%d_%H%M%S}.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",type="primary",use_container_width=True)
