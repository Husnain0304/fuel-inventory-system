from datetime import date, timedelta

import pandas as pd
import streamlit as st

from audit import record_event
from ui import page_header


SUPPLIER_MASTER_VERSION = "1.0.0"
MANAGE_ROLES = {"ADMIN", "INVENTORY_MANAGER", "PROCUREMENT_USER"}
STATUSES = ["ACTIVE", "BLOCKED", "INACTIVE"]
PAYMENT_TERMS = ["Advance paid", "Cash on delivery", "Credit 7 days", "Credit 15 days", "Credit 30 days", "Credit 45 days", "Credit 60 days", "Other"]
TRANSPORT_OPTIONS = ["Supplier delivery", "Company collection", "Third-party transporter", "Mixed"]


def ensure_supplier_master_schema(conn):
    cursor=conn.cursor()
    try:
        migrations=(
            "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS supplier_code TEXT",
            "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS legal_name TEXT",
            "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS tax_registration_number TEXT",
            "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS trade_license_number TEXT",
            "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS trade_license_expiry DATE",
            "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS country TEXT DEFAULT 'United Arab Emirates'",
            "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS emirate TEXT",
            "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS address TEXT",
            "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS primary_contact_name TEXT",
            "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS email TEXT",
            "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS phone TEXT",
            "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS payment_terms TEXT",
            "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS credit_limit REAL DEFAULT 0",
            "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS default_transport TEXT",
            "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'ACTIVE'",
            "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS compliance_notes TEXT",
            "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS created_by TEXT",
            "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP",
            "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS updated_by TEXT",
            "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP",
        )
        for statement in migrations: cursor.execute(statement)
        cursor.execute("UPDATE suppliers SET supplier_code='SUP-'||LPAD(id::text,4,'0') WHERE supplier_code IS NULL OR TRIM(supplier_code)='' ")
        cursor.execute("UPDATE suppliers SET legal_name=name WHERE legal_name IS NULL OR TRIM(legal_name)='' ")
        cursor.execute("UPDATE suppliers SET status='ACTIVE' WHERE status IS NULL")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_suppliers_code ON suppliers(supplier_code)")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_suppliers_trn ON suppliers(tax_registration_number) WHERE tax_registration_number IS NOT NULL AND TRIM(tax_registration_number)<>''")
        cursor.execute("""CREATE TABLE IF NOT EXISTS supplier_contacts(
            id BIGSERIAL PRIMARY KEY,supplier_id INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
            contact_name TEXT NOT NULL,job_title TEXT,email TEXT,phone TEXT,
            contact_type TEXT NOT NULL DEFAULT 'OPERATIONS',is_primary BOOLEAN NOT NULL DEFAULT FALSE,
            active BOOLEAN NOT NULL DEFAULT TRUE,created_by TEXT,created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP)""")
        cursor.execute("""CREATE TABLE IF NOT EXISTS supplier_products(
            supplier_id INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
            product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            approved BOOLEAN NOT NULL DEFAULT TRUE,approved_by TEXT,approved_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,PRIMARY KEY(supplier_id,product_id))""")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_suppliers_status ON suppliers(status,name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_supplier_contacts_supplier ON supplier_contacts(supplier_id,active)")
        conn.commit()
    except Exception:
        conn.rollback(); raise


def _can_manage():
    return st.session_state.get("role","VIEWER") in MANAGE_ROLES


def _suppliers(conn):
    return pd.read_sql_query("""SELECT id,supplier_code,name,legal_name,tax_registration_number,
        trade_license_number,trade_license_expiry,country,emirate,address,primary_contact_name,
        email,phone,payment_terms,credit_limit,default_transport,status,compliance_notes,
        created_by,created_at,updated_by,updated_at FROM suppliers ORDER BY name""",conn)


def _validate_profile(values):
    if len(values["name"].strip())<2: raise ValueError("Enter the supplier display name.")
    if len(values["legal_name"].strip())<2: raise ValueError("Enter the supplier legal name.")
    if values["email"] and "@" not in values["email"]: raise ValueError("Enter a valid email address or leave it blank.")
    if values["credit_limit"]<0: raise ValueError("Credit limit cannot be negative.")


def _create_supplier(conn,values,user):
    _validate_profile(values); cursor=conn.cursor()
    try:
        cursor.execute("""INSERT INTO suppliers(name,legal_name,tax_registration_number,trade_license_number,
            trade_license_expiry,country,emirate,address,primary_contact_name,email,phone,payment_terms,
            credit_limit,default_transport,status,compliance_notes,created_by,updated_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (values["name"],values["legal_name"],values["trn"] or None,values["license"] or None,
             values["license_expiry"],values["country"],values["emirate"] or None,values["address"] or None,
             values["contact"] or None,values["email"] or None,values["phone"] or None,values["payment_terms"],
             values["credit_limit"],values["transport"],values["status"],values["notes"] or None,user,user))
        supplier_id=cursor.fetchone()[0]; code=f"SUP-{supplier_id:04d}"; cursor.execute("UPDATE suppliers SET supplier_code=%s WHERE id=%s",(code,supplier_id)); conn.commit()
        record_event(conn,"CREATE_SUPPLIER","Supplier Master","Supplier",supplier_id,f"Created {code} · {values['name']}")
        return supplier_id
    except Exception:
        conn.rollback(); raise


def _update_supplier(conn,supplier_id,values,user):
    _validate_profile(values); cursor=conn.cursor()
    try:
        cursor.execute("SELECT name,legal_name,status FROM suppliers WHERE id=%s FOR UPDATE",(supplier_id,)); old=cursor.fetchone()
        if not old: raise ValueError("The supplier no longer exists.")
        cursor.execute("""UPDATE suppliers SET name=%s,legal_name=%s,tax_registration_number=%s,
            trade_license_number=%s,trade_license_expiry=%s,country=%s,emirate=%s,address=%s,
            primary_contact_name=%s,email=%s,phone=%s,payment_terms=%s,credit_limit=%s,
            default_transport=%s,status=%s,compliance_notes=%s,updated_by=%s,updated_at=CURRENT_TIMESTAMP
            WHERE id=%s""",(values["name"],values["legal_name"],values["trn"] or None,values["license"] or None,
            values["license_expiry"],values["country"],values["emirate"] or None,values["address"] or None,
            values["contact"] or None,values["email"] or None,values["phone"] or None,values["payment_terms"],
            values["credit_limit"],values["transport"],values["status"],values["notes"] or None,user,supplier_id)); conn.commit()
        record_event(conn,"UPDATE_SUPPLIER","Supplier Master","Supplier",supplier_id,f"Updated supplier profile; status {old[2]} to {values['status']}",old_values={"name":old[0],"legal_name":old[1],"status":old[2]},new_values={"name":values["name"],"legal_name":values["legal_name"],"status":values["status"]})
    except Exception:
        conn.rollback(); raise


def _profile_fields(prefix,defaults=None):
    defaults=defaults or {}; a,b=st.columns(2)
    name=a.text_input("Display name",value=str(defaults.get("name") or ""),key=f"{prefix}_name")
    legal=b.text_input("Legal company name",value=str(defaults.get("legal_name") or ""),key=f"{prefix}_legal")
    a,b,c=st.columns(3); trn=a.text_input("Tax registration number",value=str(defaults.get("tax_registration_number") or ""),key=f"{prefix}_trn"); license_no=b.text_input("Trade licence number",value=str(defaults.get("trade_license_number") or ""),key=f"{prefix}_license"); expiry_default=pd.to_datetime(defaults.get("trade_license_expiry"),errors="coerce")
    expiry=c.date_input("Trade licence expiry",value=expiry_default.date() if pd.notna(expiry_default) else date.today()+timedelta(days=365),key=f"{prefix}_expiry")
    emirates=["","Abu Dhabi","Dubai","Sharjah","Ajman","Umm Al Quwain","Ras Al Khaimah","Fujairah"]; existing_emirate=str(defaults.get("emirate") or "")
    a,b=st.columns(2); country=a.text_input("Country",value=str(defaults.get("country") or "United Arab Emirates"),key=f"{prefix}_country"); emirate=b.selectbox("Emirate",emirates,index=emirates.index(existing_emirate) if existing_emirate in emirates else 0,key=f"{prefix}_emirate")
    address=st.text_area("Registered address",value=str(defaults.get("address") or ""),key=f"{prefix}_address")
    a,b,c=st.columns(3); contact=a.text_input("Primary contact",value=str(defaults.get("primary_contact_name") or ""),key=f"{prefix}_contact"); email=b.text_input("Email",value=str(defaults.get("email") or ""),key=f"{prefix}_email"); phone=c.text_input("Phone",value=str(defaults.get("phone") or ""),key=f"{prefix}_phone")
    a,b,c=st.columns(3); existing_terms=str(defaults.get("payment_terms") or PAYMENT_TERMS[0]); terms=a.selectbox("Default payment terms",PAYMENT_TERMS,index=PAYMENT_TERMS.index(existing_terms) if existing_terms in PAYMENT_TERMS else 0,key=f"{prefix}_terms"); credit=b.number_input("Credit limit",min_value=0.0,value=float(defaults.get("credit_limit") or 0),key=f"{prefix}_credit"); existing_transport=str(defaults.get("default_transport") or TRANSPORT_OPTIONS[0]); transport=c.selectbox("Default transport",TRANSPORT_OPTIONS,index=TRANSPORT_OPTIONS.index(existing_transport) if existing_transport in TRANSPORT_OPTIONS else 0,key=f"{prefix}_transport")
    existing_status=str(defaults.get("status") or "ACTIVE"); status=st.selectbox("Supplier status",STATUSES,index=STATUSES.index(existing_status) if existing_status in STATUSES else 0,key=f"{prefix}_status"); notes=st.text_area("Compliance and control notes",value=str(defaults.get("compliance_notes") or ""),key=f"{prefix}_notes")
    return {"name":name.strip(),"legal_name":legal.strip(),"trn":trn.strip(),"license":license_no.strip(),"license_expiry":expiry,"country":country.strip(),"emirate":emirate,"address":address.strip(),"contact":contact.strip(),"email":email.strip(),"phone":phone.strip(),"payment_terms":terms,"credit_limit":float(credit),"transport":transport,"status":status,"notes":notes.strip()}


def _performance(conn):
    return pd.read_sql_query("""WITH booking_totals AS (
            SELECT supplier_id,COUNT(*) AS bookings,COALESCE(SUM(booked_liters),0) AS booked_liters
            FROM procurement_bookings GROUP BY supplier_id),
        receipt_totals AS (
            SELECT supplier_id,COUNT(*) AS receipts,COALESCE(SUM(accepted_liters),0) AS received_liters,
                COALESCE(SUM(dispatched_liters),0) AS dispatched_liters,
                COALESCE(SUM(accepted_liters-dispatched_liters),0) AS receipt_variance_liters,
                COALESCE(SUM(accepted_liters*unit_price),0) AS received_value
            FROM tank_transactions WHERE movement_category='SUPPLIER_RECEIPT' GROUP BY supplier_id),
        claim_totals AS (
            SELECT supplier_id,COUNT(*) FILTER (WHERE status NOT IN ('CLOSED','REJECTED')) AS open_claims,
                COALESCE(SUM(claim_amount) FILTER (WHERE status NOT IN ('CLOSED','REJECTED')),0) AS open_claim_value
            FROM supplier_claims GROUP BY supplier_id)
        SELECT s.id,s.supplier_code,s.name,s.status,COALESCE(b.bookings,0) AS bookings,
            COALESCE(b.booked_liters,0) AS booked_liters,COALESCE(r.receipts,0) AS receipts,
            COALESCE(r.received_liters,0) AS received_liters,COALESCE(r.dispatched_liters,0) AS dispatched_liters,
            COALESCE(r.receipt_variance_liters,0) AS receipt_variance_liters,
            COALESCE(c.open_claims,0) AS open_claims,COALESCE(c.open_claim_value,0) AS open_claim_value,
            COALESCE(r.received_value,0) AS received_value
        FROM suppliers s LEFT JOIN booking_totals b ON b.supplier_id=s.id
        LEFT JOIN receipt_totals r ON r.supplier_id=s.id LEFT JOIN claim_totals c ON c.supplier_id=s.id
        ORDER BY s.name""",conn)


def render_supplier_master(conn):
    ensure_supplier_master_schema(conn)
    from procurement import ensure_procurement_schema
    ensure_procurement_schema(conn)
    page_header("Supplier Master & Compliance","Manage approved fuel suppliers, commercial controls, contacts and performance from one register.")
    suppliers=_suppliers(conn); user=st.session_state.get("user","System"); today=pd.Timestamp(date.today()); expiry=pd.to_datetime(suppliers["trade_license_expiry"],errors="coerce") if not suppliers.empty else pd.Series(dtype="datetime64[ns]")
    active=int((suppliers["status"]=="ACTIVE").sum()) if not suppliers.empty else 0; blocked=int((suppliers["status"]=="BLOCKED").sum()) if not suppliers.empty else 0; expiring=int(((expiry>=today)&(expiry<=today+pd.Timedelta(days=30))).sum()) if not suppliers.empty else 0
    a,b,c,d=st.columns(4); a.metric("Suppliers",len(suppliers)); b.metric("Active",active); c.metric("Blocked",blocked); d.metric("Licences expiring ≤30 days",expiring)
    register,create,profile,contacts,performance=st.tabs(["Supplier register","Create supplier","Profile & status","Contacts & products","Performance & exposure"])
    with register:
        view=suppliers.copy(); view["compliance_status"]="VALID"
        if not view.empty:
            exp=pd.to_datetime(view["trade_license_expiry"],errors="coerce"); view.loc[exp<today,"compliance_status"]="EXPIRED"; view.loc[(exp>=today)&(exp<=today+pd.Timedelta(days=30)),"compliance_status"]="EXPIRING"
        st.dataframe(view[["supplier_code","name","legal_name","status","compliance_status","trade_license_expiry","tax_registration_number","payment_terms","credit_limit","primary_contact_name","email","phone"]],use_container_width=True,hide_index=True,height=470,column_config={"supplier_code":"Supplier Code","name":"Display Name","legal_name":"Legal Name","status":"Status","compliance_status":"Compliance","trade_license_expiry":"Licence Expiry","tax_registration_number":"TRN","payment_terms":"Payment Terms","credit_limit":st.column_config.NumberColumn("Credit Limit",format="%.2f"),"primary_contact_name":"Contact","email":"Email","phone":"Phone"})
        st.caption("Blocked and inactive suppliers remain in historical records but are removed from new booking, receipt and uplift selections.")
    with create:
        if not _can_manage(): st.info("Supplier-management permission is required to create a profile.")
        with st.form("create_supplier",clear_on_submit=True):
            values=_profile_fields("create"); submit=st.form_submit_button("Create supplier profile",type="primary",disabled=not _can_manage())
        if submit:
            try: supplier_id=_create_supplier(conn,values,user); st.success(f"SUP-{supplier_id:04d} created successfully."); st.rerun()
            except Exception as error: st.error(str(error))
    with profile:
        if suppliers.empty: st.info("Create the first supplier profile.")
        else:
            supplier_map={f"{r.supplier_code} · {r.name}":int(r.id) for r in suppliers.itertuples()}; selected=st.selectbox("Supplier profile",list(supplier_map),key="supplier_profile_selector"); supplier_id=supplier_map[selected]; current=suppliers[suppliers["id"]==supplier_id].iloc[0].to_dict()
            st.info(f"Supplier ID {supplier_id} · Use this ID when linking evidence in the Evidence Centre.")
            with st.form("update_supplier"):
                values=_profile_fields(f"update_{supplier_id}",current); save=st.form_submit_button("Save supplier profile",type="primary",disabled=not _can_manage())
            if save:
                try: _update_supplier(conn,supplier_id,values,user); st.success("Supplier profile updated."); st.rerun()
                except Exception as error: st.error(str(error))
    with contacts:
        if suppliers.empty: st.info("Create a supplier before adding contacts or products.")
        else:
            supplier_map={f"{r.supplier_code} · {r.name}":int(r.id) for r in suppliers.itertuples()}; selected=st.selectbox("Supplier",list(supplier_map),key="supplier_contact_selector"); supplier_id=supplier_map[selected]
            st.subheader("Contact directory"); contact_data=pd.read_sql_query("SELECT id,contact_name,job_title,contact_type,email,phone,is_primary,active,created_by,created_at FROM supplier_contacts WHERE supplier_id=%s ORDER BY is_primary DESC,contact_name",conn,params=[supplier_id]); st.dataframe(contact_data,use_container_width=True,hide_index=True)
            with st.form("supplier_contact",clear_on_submit=True):
                a,b=st.columns(2); contact_name=a.text_input("Contact name"); job=b.text_input("Job title"); a,b,c=st.columns(3); contact_type=a.selectbox("Contact type",["OPERATIONS","COMMERCIAL","FINANCE","QUALITY","MANAGEMENT"]); email=b.text_input("Contact email"); phone=c.text_input("Contact phone"); primary=st.checkbox("Primary contact"); add_contact=st.form_submit_button("Add contact",disabled=not _can_manage())
            if add_contact:
                if len(contact_name.strip())<2 or (email and "@" not in email): st.error("Enter a contact name and valid email address.")
                else:
                    cursor=conn.cursor()
                    if primary: cursor.execute("UPDATE supplier_contacts SET is_primary=FALSE WHERE supplier_id=%s",(supplier_id,))
                    cursor.execute("""INSERT INTO supplier_contacts(supplier_id,contact_name,job_title,email,phone,contact_type,is_primary,created_by)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",(supplier_id,contact_name.strip(),job.strip() or None,email.strip() or None,phone.strip() or None,contact_type,primary,user)); contact_id=cursor.fetchone()[0]; conn.commit(); record_event(conn,"ADD_SUPPLIER_CONTACT","Supplier Master","Supplier Contact",contact_id,f"Added contact to supplier {supplier_id}"); st.success("Contact added."); st.rerun()
            st.subheader("Approved fuel products"); products=pd.read_sql_query("SELECT id,name FROM products WHERE active=TRUE ORDER BY name",conn); approved=pd.read_sql_query("SELECT product_id FROM supplier_products WHERE supplier_id=%s AND approved=TRUE",conn,params=[supplier_id]); current_ids=set(approved["product_id"].astype(int).tolist()) if not approved.empty else set(); product_map=dict(zip(products["name"],products["id"])); selected_products=st.multiselect("Products approved for this supplier",list(product_map),default=[name for name,pid in product_map.items() if int(pid) in current_ids],disabled=not _can_manage())
            if st.button("Save approved products",type="primary",disabled=not _can_manage()):
                cursor=conn.cursor(); cursor.execute("UPDATE supplier_products SET approved=FALSE WHERE supplier_id=%s",(supplier_id,))
                for name in selected_products: cursor.execute("""INSERT INTO supplier_products(supplier_id,product_id,approved,approved_by) VALUES (%s,%s,TRUE,%s)
                    ON CONFLICT(supplier_id,product_id) DO UPDATE SET approved=TRUE,approved_by=EXCLUDED.approved_by,approved_at=CURRENT_TIMESTAMP""",(supplier_id,int(product_map[name]),user))
                conn.commit(); record_event(conn,"UPDATE_SUPPLIER_PRODUCTS","Supplier Master","Supplier",supplier_id,f"Approved products: {', '.join(selected_products) or 'None'}"); st.success("Approved products saved."); st.rerun()
    with performance:
        data=_performance(conn)
        if data.empty: st.info("No supplier performance data is available.")
        else:
            data["receipt_match_percent"]=data.apply(lambda r:(r["received_liters"]/r["dispatched_liters"]*100) if float(r["dispatched_liters"] or 0)>0 else None,axis=1)
            st.dataframe(data,use_container_width=True,hide_index=True,height=480,column_config={"supplier_code":"Supplier Code","name":"Supplier","status":"Status","booked_liters":st.column_config.NumberColumn("Booked",format="%.2f L"),"received_liters":st.column_config.NumberColumn("Received",format="%.2f L"),"receipt_variance_liters":st.column_config.NumberColumn("Receipt Variance",format="%.2f L"),"open_claim_value":st.column_config.NumberColumn("Open Claims",format="%.2f"),"received_value":st.column_config.NumberColumn("Received Value",format="%.2f"),"receipt_match_percent":st.column_config.NumberColumn("Receipt Match",format="%.2f%%")})
            st.caption("Performance is calculated from recorded bookings, accepted supplier receipts and supplier claims.")
