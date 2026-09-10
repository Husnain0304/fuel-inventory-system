import re

import streamlit as st

ROLES = ["ADMIN", "INVENTORY_MANAGER", "STOREKEEPER", "PROCUREMENT_USER", "APPROVER", "AUDITOR", "VIEWER", "OPERATOR"]
ROLE_LABELS = {"ADMIN": "Administrator", "INVENTORY_MANAGER": "Inventory Manager", "STOREKEEPER": "Storekeeper", "PROCUREMENT_USER": "Procurement User", "APPROVER": "Approver", "AUDITOR": "Auditor", "VIEWER": "Read-only Viewer", "OPERATOR": "Legacy Operator"}
ALL_PAGES = {"Command Centre", "Fuel Operations", "Fleet Inventory", "Inventory Control", "Measurement & Loss Control", "Transaction Control", "Depots & Storage", "Storage Operations", "Stock in Transit", "Supplier Procurement", "Supplier Master", "Supplier Scorecards", "Receipt Costing", "Product & Quality", "Batch Aging & FEFO", "Stock Commitments", "Inventory Forecasting", "Financial Valuation", "Month-End Closing", "Inventory Health", "Evidence Centre", "Truck Ledger", "Integration Inbox", "Approvals", "Notifications", "Report Centre", "Audit Centre", "Configuration", "User Access"}
ALL_ACTIONS = {"VIEW", "CREATE", "EDIT", "IMPORT", "EXPORT", "APPROVE", "REJECT", "POST_MOVEMENT", "POST_RECEIPT", "POST_TRANSFER", "RECONCILE", "CREATE_BOOKING", "CREATE_RELEASE", "UPDATE_CLAIM", "REVIEW_RECONCILIATION", "REVIEW_CHANGE", "MANAGE_DOCUMENTS", "VIEW_RESTRICTED_DOCUMENTS", "MANAGE_QUALITY", "DECIDE_QUALITY", "EDIT_BATCH", "MANAGE_SUPPLIERS"}
PAGE_PERMISSIONS = {
    "INVENTORY_MANAGER": ALL_PAGES - {"User Access", "Configuration"},
    "STOREKEEPER": {"Command Centre", "Fuel Operations", "Fleet Inventory", "Inventory Control", "Measurement & Loss Control", "Depots & Storage", "Storage Operations", "Stock in Transit", "Product & Quality", "Batch Aging & FEFO", "Stock Commitments", "Evidence Centre", "Truck Ledger", "Integration Inbox", "Notifications", "Report Centre"},
    "PROCUREMENT_USER": {"Command Centre", "Supplier Procurement", "Supplier Master", "Supplier Scorecards", "Receipt Costing", "Product & Quality", "Storage Operations", "Inventory Forecasting", "Financial Valuation", "Evidence Centre", "Notifications", "Report Centre"},
    "APPROVER": {"Command Centre", "Inventory Control", "Measurement & Loss Control", "Transaction Control", "Approvals", "Supplier Procurement", "Supplier Master", "Supplier Scorecards", "Receipt Costing", "Product & Quality", "Month-End Closing", "Inventory Health", "Evidence Centre", "Notifications", "Report Centre", "Audit Centre"},
    "AUDITOR": {"Command Centre", "Measurement & Loss Control", "Transaction Control", "Stock in Transit", "Supplier Procurement", "Supplier Master", "Supplier Scorecards", "Receipt Costing", "Product & Quality", "Batch Aging & FEFO", "Stock Commitments", "Inventory Forecasting", "Financial Valuation", "Month-End Closing", "Inventory Health", "Evidence Centre", "Truck Ledger", "Notifications", "Report Centre", "Audit Centre"},
    "VIEWER": {"Command Centre", "Product & Quality", "Batch Aging & FEFO", "Stock Commitments", "Inventory Forecasting", "Financial Valuation", "Month-End Closing", "Evidence Centre", "Truck Ledger", "Notifications", "Report Centre"},
    "OPERATOR": {"Command Centre", "Fuel Operations", "Fleet Inventory", "Measurement & Loss Control", "Storage Operations", "Stock in Transit", "Product & Quality", "Batch Aging & FEFO", "Stock Commitments", "Evidence Centre", "Truck Ledger", "Integration Inbox", "Approvals", "Notifications", "Report Centre"},
}
ACTION_PERMISSIONS = {
    "ADMIN": {"*"}, "INVENTORY_MANAGER": {"*"},
    "STOREKEEPER": {"VIEW", "CREATE", "EDIT", "POST_MOVEMENT", "POST_RECEIPT", "POST_TRANSFER", "RECONCILE", "IMPORT", "EXPORT", "MANAGE_DOCUMENTS", "MANAGE_QUALITY", "EDIT_BATCH"},
    "PROCUREMENT_USER": {"VIEW", "CREATE", "EDIT", "EXPORT", "CREATE_BOOKING", "CREATE_RELEASE", "UPDATE_CLAIM", "POST_RECEIPT", "MANAGE_DOCUMENTS", "MANAGE_QUALITY", "MANAGE_SUPPLIERS"},
    "APPROVER": {"VIEW", "EXPORT", "APPROVE", "REJECT", "REVIEW_RECONCILIATION", "REVIEW_CHANGE", "DECIDE_QUALITY", "VIEW_RESTRICTED_DOCUMENTS"},
    "AUDITOR": {"VIEW", "EXPORT", "VIEW_RESTRICTED_DOCUMENTS"}, "VIEWER": {"VIEW", "EXPORT"},
    "OPERATOR": {"VIEW", "CREATE", "EDIT", "EXPORT", "POST_MOVEMENT", "POST_RECEIPT", "POST_TRANSFER", "IMPORT", "MANAGE_DOCUMENTS", "MANAGE_QUALITY", "EDIT_BATCH"},
}

def role_code(name):
    return re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")[:50]

def ensure_rbac_schema(conn):
    cursor = conn.cursor()
    try:
        cursor.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check")
        cursor.execute("CREATE TABLE IF NOT EXISTS security_role_changes(id BIGSERIAL PRIMARY KEY,user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,old_role TEXT,new_role TEXT,changed_by TEXT,changed_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP)")
        cursor.execute("CREATE TABLE IF NOT EXISTS security_roles(role_code TEXT PRIMARY KEY,role_name TEXT NOT NULL UNIQUE,description TEXT,is_system BOOLEAN NOT NULL DEFAULT FALSE,active BOOLEAN NOT NULL DEFAULT TRUE,created_by TEXT,created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        cursor.execute("CREATE TABLE IF NOT EXISTS security_role_pages(role_code TEXT NOT NULL REFERENCES security_roles(role_code) ON DELETE CASCADE,page_name TEXT NOT NULL,PRIMARY KEY(role_code,page_name))")
        cursor.execute("CREATE TABLE IF NOT EXISTS security_role_actions(role_code TEXT NOT NULL REFERENCES security_roles(role_code) ON DELETE CASCADE,action_name TEXT NOT NULL,PRIMARY KEY(role_code,action_name))")
        cursor.execute("CREATE TABLE IF NOT EXISTS security_user_overrides(user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,permission_type TEXT NOT NULL CHECK(permission_type IN ('PAGE','ACTION')),permission_name TEXT NOT NULL,effect TEXT NOT NULL CHECK(effect IN ('ALLOW','DENY')),updated_by TEXT,updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(user_id,permission_type,permission_name))")
        for code in ROLES:
            cursor.execute("INSERT INTO security_roles(role_code,role_name,description,is_system,created_by) VALUES(%s,%s,'Built-in role',TRUE,'System') ON CONFLICT(role_code) DO NOTHING RETURNING role_code", (code, ROLE_LABELS[code]))
            if not cursor.fetchone():
                continue
            pages = ALL_PAGES if code == "ADMIN" else PAGE_PERMISSIONS.get(code, set())
            actions = ALL_ACTIONS if code == "ADMIN" or "*" in ACTION_PERMISSIONS.get(code, set()) else ACTION_PERMISSIONS.get(code, set())
            for item in pages: cursor.execute("INSERT INTO security_role_pages(role_code,page_name) VALUES(%s,%s) ON CONFLICT DO NOTHING", (code, item))
            for item in actions: cursor.execute("INSERT INTO security_role_actions(role_code,action_name) VALUES(%s,%s) ON CONFLICT DO NOTHING", (code, item))
        conn.commit()
    except Exception:
        conn.rollback(); raise

def role_catalog(conn, active_only=True):
    cursor = conn.cursor(); sql = "SELECT role_code,role_name,description,is_system,active FROM security_roles"
    if active_only: sql += " WHERE active=TRUE"
    cursor.execute(sql + " ORDER BY is_system DESC,role_name"); return cursor.fetchall()

def role_permissions(conn, code):
    cursor = conn.cursor(); cursor.execute("SELECT page_name FROM security_role_pages WHERE role_code=%s", (code,)); pages = {r[0] for r in cursor.fetchall()}
    cursor.execute("SELECT action_name FROM security_role_actions WHERE role_code=%s", (code,)); return pages, {r[0] for r in cursor.fetchall()}

def load_effective_permissions(conn):
    role, user_id = st.session_state.get("role", "VIEWER"), st.session_state.get("user_id")
    if role == "ADMIN": pages, actions = set(ALL_PAGES), set(ALL_ACTIONS)
    else:
        pages, actions = role_permissions(conn, role)
        if not pages and role in PAGE_PERMISSIONS: pages = set(PAGE_PERMISSIONS[role])
        if not actions and role in ACTION_PERMISSIONS: actions = set(ACTION_PERMISSIONS[role])
        if user_id:
            cursor = conn.cursor(); cursor.execute("SELECT permission_type,permission_name,effect FROM security_user_overrides WHERE user_id=%s", (user_id,))
            for kind, name, effect in cursor.fetchall():
                target = pages if kind == "PAGE" else actions
                target.add(name) if effect == "ALLOW" else target.discard(name)
    pages.add("Command Centre")
    st.session_state["_rbac_pages"], st.session_state["_rbac_actions"] = pages, actions

def allowed_pages(role):
    return set(ALL_PAGES) if role == "ADMIN" else set(st.session_state.get("_rbac_pages", PAGE_PERMISSIONS.get(role, set())))

def can(role, action):
    if role == "ADMIN": return True
    permissions = set(st.session_state.get("_rbac_actions", ACTION_PERMISSIONS.get(role, set())))
    return "*" in permissions or action in permissions

def require_permission(action):
    if not can(st.session_state.get("role", "VIEWER"), action):
        st.error("You do not have permission to perform this action."); st.stop()
