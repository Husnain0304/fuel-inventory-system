import streamlit as st

ROLES=["ADMIN","INVENTORY_MANAGER","STOREKEEPER","PROCUREMENT_USER","APPROVER","AUDITOR","VIEWER","OPERATOR"]
ROLE_LABELS={"ADMIN":"Administrator","INVENTORY_MANAGER":"Inventory Manager","STOREKEEPER":"Storekeeper","PROCUREMENT_USER":"Procurement User","APPROVER":"Approver","AUDITOR":"Auditor","VIEWER":"Read-only Viewer","OPERATOR":"Legacy Operator"}
ALL_PAGES={"Command Centre","Fuel Operations","Fleet Inventory","Inventory Control","Transaction Control","Depots & Storage","Storage Operations","Supplier Procurement","Supplier Master","Supplier Scorecards","Inventory Forecasting","Financial Valuation","Month-End Closing","Evidence Centre","Truck Ledger","Integration Inbox","Approvals","Notifications","Report Centre","Audit Centre","Configuration","User Access"}
PAGE_PERMISSIONS={
 "INVENTORY_MANAGER":ALL_PAGES-{"User Access","Configuration"},
 "STOREKEEPER":{"Command Centre","Fuel Operations","Fleet Inventory","Inventory Control","Depots & Storage","Storage Operations","Evidence Centre","Truck Ledger","Integration Inbox","Notifications","Report Centre"},
 "PROCUREMENT_USER":{"Command Centre","Supplier Procurement","Supplier Master","Supplier Scorecards","Storage Operations","Inventory Forecasting","Financial Valuation","Evidence Centre","Notifications","Report Centre"},
 "APPROVER":{"Command Centre","Inventory Control","Transaction Control","Approvals","Supplier Procurement","Supplier Master","Supplier Scorecards","Month-End Closing","Evidence Centre","Notifications","Report Centre","Audit Centre"},
 "AUDITOR":{"Command Centre","Fleet Inventory","Inventory Control","Transaction Control","Depots & Storage","Supplier Procurement","Supplier Master","Supplier Scorecards","Inventory Forecasting","Financial Valuation","Month-End Closing","Evidence Centre","Truck Ledger","Notifications","Report Centre","Audit Centre"},
 "VIEWER":{"Command Centre","Fleet Inventory","Depots & Storage","Inventory Forecasting","Financial Valuation","Month-End Closing","Evidence Centre","Truck Ledger","Notifications","Report Centre"},
 "OPERATOR":{"Command Centre","Fuel Operations","Fleet Inventory","Storage Operations","Evidence Centre","Truck Ledger","Integration Inbox","Approvals","Notifications","Report Centre"},
}
ACTION_PERMISSIONS={
 "ADMIN":{"*"},"INVENTORY_MANAGER":{"*"},
 "STOREKEEPER":{"POST_MOVEMENT","POST_RECEIPT","POST_TRANSFER","RECONCILE","IMPORT"},
 "PROCUREMENT_USER":{"CREATE_BOOKING","CREATE_RELEASE","UPDATE_CLAIM","POST_RECEIPT"},
 "APPROVER":{"APPROVE","REJECT","REVIEW_RECONCILIATION","REVIEW_CHANGE"},
 "AUDITOR":{"VIEW","EXPORT"},"VIEWER":{"VIEW","EXPORT"},
 "OPERATOR":{"POST_MOVEMENT","POST_RECEIPT","POST_TRANSFER","IMPORT","VIEW","EXPORT"},
}

def ensure_rbac_schema(conn):
 cursor=conn.cursor()
 try:
  cursor.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check")
  cursor.execute("""CREATE TABLE IF NOT EXISTS security_role_changes(id BIGSERIAL PRIMARY KEY,user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,old_role TEXT,new_role TEXT,changed_by TEXT,changed_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP)""")
  conn.commit()
 except Exception: conn.rollback(); raise

def allowed_pages(role):
 return ALL_PAGES if role=="ADMIN" else PAGE_PERMISSIONS.get(role,set())

def can(role,action):
 permissions=ACTION_PERMISSIONS.get(role,set()); return "*" in permissions or action in permissions

def require_permission(action):
 if not can(st.session_state.get("role","VIEWER"),action): st.error("You do not have permission to perform this action."); st.stop()
