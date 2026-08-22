from datetime import date
import hashlib
import mimetypes

import pandas as pd
import streamlit as st

from audit import record_event
from ui import page_header


DOCUMENT_CATEGORIES = [
    "Supplier Invoice", "Delivery Note", "Weighbridge Slip", "Tank Dip Sheet",
    "Meter Reading", "Purchase Order", "Booking Confirmation", "Credit Note",
    "Quality Certificate", "Approval Evidence", "Reconciliation Evidence",
    "Month-End Evidence", "Contract", "Photograph", "Other",
]

LINK_TYPES = {
    "General / Unlinked": (None, None),
    "Truck Transaction (TX)": ("TRUCK_TRANSACTION", "transactions"),
    "Tank Transaction (STX)": ("TANK_TRANSACTION", "tank_transactions"),
    "Approval Request (AP)": ("APPROVAL_REQUEST", "approval_requests"),
    "Supplier Booking (BK)": ("BOOKING", "procurement_bookings"),
    "Supplier Release (RL)": ("RELEASE", "procurement_releases"),
    "Supplier Claim (CL)": ("CLAIM", "supplier_claims"),
    "Reconciliation (RC)": ("RECONCILIATION", "stock_reconciliations"),
    "Inventory Period (PC)": ("INVENTORY_PERIOD", "inventory_periods"),
    "Supplier": ("SUPPLIER", "suppliers"),
    "Depot": ("DEPOT", "depots"),
    "Storage Tank": ("STORAGE_TANK", "storage_tanks"),
    "Truck": ("TRUCK", "trucks"),
}

ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "xlsx", "xls", "csv", "docx", "txt"}
MAX_FILE_SIZE = 8 * 1024 * 1024
MANAGE_ROLES = {"ADMIN", "INVENTORY_MANAGER", "STOREKEEPER", "PROCUREMENT_USER", "OPERATOR"}
RESTRICTED_ROLES = {"ADMIN", "INVENTORY_MANAGER", "APPROVER", "AUDITOR"}


def ensure_document_schema(conn):
    cursor = conn.cursor()
    try:
        cursor.execute("""CREATE TABLE IF NOT EXISTS document_records(
            id BIGSERIAL PRIMARY KEY, title TEXT NOT NULL, category TEXT NOT NULL,
            document_date DATE, external_reference TEXT, description TEXT,
            entity_type TEXT, entity_id BIGINT, supplier_id INTEGER REFERENCES suppliers(id),
            confidentiality TEXT NOT NULL DEFAULT 'INTERNAL'
                CHECK(confidentiality IN ('INTERNAL','RESTRICTED')),
            status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','ARCHIVED')),
            current_version INTEGER NOT NULL DEFAULT 1, created_by TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            archived_by TEXT, archived_at TIMESTAMPTZ, archive_reason TEXT)""")
        cursor.execute("""CREATE TABLE IF NOT EXISTS document_versions(
            id BIGSERIAL PRIMARY KEY, document_id BIGINT NOT NULL REFERENCES document_records(id) ON DELETE RESTRICT,
            version_number INTEGER NOT NULL, file_name TEXT NOT NULL, mime_type TEXT NOT NULL,
            file_size BIGINT NOT NULL, sha256 TEXT NOT NULL, file_content BYTEA NOT NULL,
            version_note TEXT, uploaded_by TEXT NOT NULL,
            uploaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(document_id,version_number))""")
        cursor.execute("""CREATE TABLE IF NOT EXISTS document_access_log(
            id BIGSERIAL PRIMARY KEY, document_id BIGINT NOT NULL REFERENCES document_records(id) ON DELETE RESTRICT,
            version_number INTEGER, action TEXT NOT NULL, username TEXT NOT NULL,
            action_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, detail TEXT)""")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_documents_entity ON document_records(entity_type,entity_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_documents_supplier ON document_records(supplier_id,document_date DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_documents_status ON document_records(status,created_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_document_versions_document ON document_versions(document_id,version_number DESC)")
        conn.commit()
    except Exception:
        conn.rollback(); raise


def _can_manage():
    return st.session_state.get("role", "VIEWER") in MANAGE_ROLES


def _can_read(confidentiality):
    return confidentiality != "RESTRICTED" or st.session_state.get("role", "VIEWER") in RESTRICTED_ROLES


def _validate_link(conn, link_label, record_id):
    entity_type, table = LINK_TYPES[link_label]
    if entity_type is None:
        return None, None
    if not record_id or int(record_id) <= 0:
        raise ValueError("Enter the numeric record ID shown after TX-, STX-, AP-, BK-, RL-, CL-, RC- or PC-.")
    cursor = conn.cursor(); cursor.execute(f"SELECT id FROM {table} WHERE id=%s", (int(record_id),))
    if not cursor.fetchone():
        raise ValueError(f"Record {record_id} was not found for {link_label}.")
    return entity_type, int(record_id)


def _validate_file(uploaded):
    if uploaded is None:
        raise ValueError("Choose a supporting file.")
    extension = uploaded.name.rsplit(".", 1)[-1].lower() if "." in uploaded.name else ""
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("Allowed files: PDF, images, Excel, CSV, Word and text.")
    content = uploaded.getvalue()
    if not content:
        raise ValueError("The selected file is empty.")
    if len(content) > MAX_FILE_SIZE:
        raise ValueError("The file is larger than 8 MB. Compress it before uploading.")
    mime = uploaded.type or mimetypes.guess_type(uploaded.name)[0] or "application/octet-stream"
    return content, mime, hashlib.sha256(content).hexdigest()


def _access(conn, document_id, version, action, detail=""):
    cursor = conn.cursor(); cursor.execute("""INSERT INTO document_access_log
        (document_id,version_number,action,username,detail) VALUES (%s,%s,%s,%s,%s)""",
        (document_id,version,action,st.session_state.get("user","System"),detail or None)); conn.commit()


def _documents(conn):
    return pd.read_sql_query("""SELECT d.id,CONCAT('DOC-',d.id) AS document_number,d.title,d.category,
        d.document_date,d.external_reference,d.entity_type,d.entity_id,s.name AS supplier,
        d.confidentiality,d.status,d.current_version,d.created_by,d.created_at,
        v.file_name,v.file_size,v.mime_type,v.sha256,v.uploaded_at
        FROM document_records d LEFT JOIN suppliers s ON s.id=d.supplier_id
        LEFT JOIN document_versions v ON v.document_id=d.id AND v.version_number=d.current_version
        ORDER BY d.id DESC""", conn)


def _create_document(conn, values, uploaded, user):
    content,mime,digest=_validate_file(uploaded); entity_type,entity_id=_validate_link(conn,values["link_label"],values["entity_id"])
    cursor=conn.cursor()
    try:
        cursor.execute("""INSERT INTO document_records(title,category,document_date,external_reference,
            description,entity_type,entity_id,supplier_id,confidentiality,created_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (values["title"],values["category"],values["document_date"],values["reference"] or None,
             values["description"] or None,entity_type,entity_id,values["supplier_id"],values["confidentiality"],user))
        document_id=cursor.fetchone()[0]
        cursor.execute("""INSERT INTO document_versions(document_id,version_number,file_name,mime_type,
            file_size,sha256,file_content,version_note,uploaded_by) VALUES (%s,1,%s,%s,%s,%s,%s,%s,%s)""",
            (document_id,uploaded.name,mime,len(content),digest,content,"Original evidence",user)); conn.commit()
        record_event(conn,"UPLOAD_DOCUMENT","Evidence Centre","Document",document_id,f"Uploaded {uploaded.name}; linked to {entity_type or 'GENERAL'} {entity_id or ''}")
        _access(conn,document_id,1,"UPLOAD",uploaded.name)
        return document_id
    except Exception:
        conn.rollback(); raise


def _add_version(conn, document_id, uploaded, note, user):
    content,mime,digest=_validate_file(uploaded); cursor=conn.cursor()
    try:
        cursor.execute("SELECT status,current_version FROM document_records WHERE id=%s FOR UPDATE",(document_id,)); row=cursor.fetchone()
        if not row or row[0]!="ACTIVE": raise ValueError("Only an active document can receive a new version.")
        version=int(row[1])+1
        cursor.execute("""INSERT INTO document_versions(document_id,version_number,file_name,mime_type,
            file_size,sha256,file_content,version_note,uploaded_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (document_id,version,uploaded.name,mime,len(content),digest,content,note,user))
        cursor.execute("UPDATE document_records SET current_version=%s WHERE id=%s",(version,document_id)); conn.commit()
        record_event(conn,"ADD_DOCUMENT_VERSION","Evidence Centre","Document",document_id,f"Added version {version}: {uploaded.name}")
        _access(conn,document_id,version,"ADD_VERSION",note)
        return version
    except Exception:
        conn.rollback(); raise


def _archive(conn, document_id, reason, user):
    cursor=conn.cursor(); cursor.execute("""UPDATE document_records SET status='ARCHIVED',archived_by=%s,
        archived_at=CURRENT_TIMESTAMP,archive_reason=%s WHERE id=%s AND status='ACTIVE'""",(user,reason,document_id))
    if cursor.rowcount!=1: conn.rollback(); raise ValueError("This document is already archived or no longer exists.")
    conn.commit(); record_event(conn,"ARCHIVE_DOCUMENT","Evidence Centre","Document",document_id,reason)
    _access(conn,document_id,None,"ARCHIVE",reason)


def _render_register(conn, documents):
    if documents.empty: st.info("No evidence documents are registered yet."); return
    a,b,c,d=st.columns([1,1,1,2]); status=a.multiselect("Status",sorted(documents["status"].unique())); category=b.multiselect("Category",sorted(documents["category"].unique())); link=c.multiselect("Linked record",sorted(documents["entity_type"].dropna().unique())); search=d.text_input("Search documents")
    view=documents.copy()
    if status: view=view[view["status"].isin(status)]
    if category: view=view[view["category"].isin(category)]
    if link: view=view[view["entity_type"].isin(link)]
    if search.strip(): view=view[view.astype(str).agg(" ".join,axis=1).str.contains(search.strip(),case=False,na=False)]
    role=st.session_state.get("role","VIEWER"); view=view[(view["confidentiality"]!="RESTRICTED") | role in RESTRICTED_ROLES]
    st.dataframe(view.drop(columns=["sha256","mime_type"],errors="ignore"),use_container_width=True,hide_index=True,height=440,
        column_config={"file_size":st.column_config.NumberColumn("File size",format="%d bytes"),"current_version":st.column_config.NumberColumn("Version",format="v%d")})


def render_document_centre(conn):
    ensure_document_schema(conn); page_header("Document & Evidence Centre","Keep every operational and financial document linked, versioned and audit-ready.")
    user=st.session_state.get("user","System"); documents=_documents(conn); active=int((documents["status"]=="ACTIVE").sum()) if not documents.empty else 0; restricted=int((documents["confidentiality"]=="RESTRICTED").sum()) if not documents.empty else 0
    a,b,c=st.columns(3); a.metric("Registered documents",len(documents)); b.metric("Active evidence",active); c.metric("Restricted",restricted)
    register,upload,record,activity=st.tabs(["Document register","Upload evidence","Open document","Access history"])
    with register: _render_register(conn,documents)
    with upload:
        if not _can_manage(): st.info("Your role can review evidence but cannot upload or change it.")
        suppliers=pd.read_sql_query("SELECT id,name FROM suppliers ORDER BY name",conn); supplier_options={"Not supplier-specific":None,**dict(zip(suppliers["name"],suppliers["id"]))}
        with st.form("new_document",clear_on_submit=True):
            x,y=st.columns(2); title=x.text_input("Document title"); category=y.selectbox("Category",DOCUMENT_CATEGORIES)
            x,y=st.columns(2); document_date=x.date_input("Document date",date.today()); reference=y.text_input("External reference / invoice number")
            x,y=st.columns(2); link_label=x.selectbox("Link document to",list(LINK_TYPES)); entity_id=y.number_input("Record ID",min_value=0,step=1,help="Example: enter 125 for TX-125. Leave 0 only for General / Unlinked.")
            confidentiality_options=["INTERNAL","RESTRICTED"] if st.session_state.get("role") in RESTRICTED_ROLES else ["INTERNAL"]
            x,y=st.columns(2); supplier=x.selectbox("Supplier",list(supplier_options)); confidentiality=y.selectbox("Confidentiality",confidentiality_options)
            description=st.text_area("Description"); uploaded=st.file_uploader("Supporting file",type=sorted(ALLOWED_EXTENSIONS),key="new_evidence_file"); submit=st.form_submit_button("Register evidence",type="primary",disabled=not _can_manage())
        if submit:
            if len(title.strip())<3: st.error("Enter a clear document title.")
            else:
                try:
                    document_id=_create_document(conn,{"title":title.strip(),"category":category,"document_date":document_date,"reference":reference.strip(),"description":description.strip(),"link_label":link_label,"entity_id":int(entity_id),"supplier_id":supplier_options[supplier],"confidentiality":confidentiality},uploaded,user)
                    st.success(f"DOC-{document_id} registered successfully and added to the audit trail."); st.rerun()
                except Exception as error: st.error(str(error))
    with record:
        if documents.empty: st.info("Upload the first evidence document to open it here.")
        else:
            visible=documents[documents.apply(lambda row:_can_read(row["confidentiality"]),axis=1)]
            if visible.empty: st.info("No documents are available for your role.")
            else:
                choices={f"{r.document_number} · {r.title} · v{r.current_version}":int(r.id) for r in visible.itertuples()}; chosen=st.selectbox("Document",list(choices)); document_id=choices[chosen]; item=visible[visible["id"]==document_id].iloc[0]
                st.markdown(f"### {item['document_number']} · {item['title']}"); st.caption(f"{item['category']} · {item['status']} · {item['confidentiality']} · Created by {item['created_by']}")
                versions=pd.read_sql_query("SELECT version_number,file_name,mime_type,file_size,sha256,version_note,uploaded_by,uploaded_at FROM document_versions WHERE document_id=%s ORDER BY version_number DESC",conn,params=[document_id]); st.dataframe(versions.drop(columns=["sha256"]),use_container_width=True,hide_index=True)
                version=int(st.selectbox("Version to download",versions["version_number"].tolist())); cursor=conn.cursor(); cursor.execute("SELECT file_name,mime_type,file_content FROM document_versions WHERE document_id=%s AND version_number=%s",(document_id,version)); file_name,mime,content=cursor.fetchone()
                if st.download_button(f"Download {file_name}",bytes(content),file_name,mime,type="primary"):
                    _access(conn,document_id,version,"DOWNLOAD",file_name); record_event(conn,"DOWNLOAD_DOCUMENT","Evidence Centre","Document",document_id,f"Downloaded version {version}: {file_name}")
                if _can_manage() and item["status"]=="ACTIVE":
                    with st.expander("Add a replacement version"):
                        replacement=st.file_uploader("New file",type=sorted(ALLOWED_EXTENSIONS),key=f"version_file_{document_id}"); note=st.text_input("Version reason",key=f"version_note_{document_id}")
                        if st.button("Add new version",key=f"add_version_{document_id}"):
                            if len(note.strip())<5: st.error("Enter why this version is being added.")
                            else:
                                try: new_version=_add_version(conn,document_id,replacement,note.strip(),user); st.success(f"Version {new_version} added. Earlier versions remain available."); st.rerun()
                                except Exception as error: st.error(str(error))
                    with st.expander("Archive document"):
                        archive_reason=st.text_input("Archive reason",key=f"archive_reason_{document_id}")
                        if st.button("Archive without deleting",key=f"archive_{document_id}"):
                            if len(archive_reason.strip())<5: st.error("Enter a clear archive reason.")
                            else:
                                try: _archive(conn,document_id,archive_reason.strip(),user); st.success("Document archived. Its files and history remain available."); st.rerun()
                                except Exception as error: st.error(str(error))
    with activity:
        history=pd.read_sql_query("""SELECT l.action_at AS "Date & Time",CONCAT('DOC-',l.document_id) AS "Document",
            l.version_number AS "Version",l.action AS "Action",l.username AS "User",l.detail AS "Detail"
            FROM document_access_log l ORDER BY l.id DESC LIMIT 1000""",conn)
        if history.empty: st.info("No document access activity has been recorded yet.")
        else: st.dataframe(history,use_container_width=True,hide_index=True,height=500)
