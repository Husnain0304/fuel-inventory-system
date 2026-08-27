import streamlit as st

from approval_workflow import ensure_approval_schema
from batch_aging import ensure_batch_aging_schema
from document_centre import ensure_document_schema
from period_close import ensure_period_close_schema
from procurement import ensure_procurement_schema
from product_quality import ensure_quality_schema
from receipt_costing import ensure_receipt_cost_schema
from rbac import ensure_rbac_schema
from stock_reservations import ensure_reservation_schema
from stock_transit import ensure_transit_schema
from storage_control import ensure_storage_control_schema
from supplier_master import ensure_supplier_master_schema
from supplier_scorecards import ensure_scorecard_schema
from user_notifications import ensure_notification_schema
from valuation import ensure_valuation_schema


@st.cache_resource(show_spinner="Preparing inventory controls…")
def initialize_application_schema(_conn):
    """Run idempotent migrations once per Streamlit process, not once per user session."""
    ensure_rbac_schema(_conn)
    ensure_approval_schema(_conn)
    ensure_procurement_schema(_conn)
    ensure_valuation_schema(_conn)
    ensure_period_close_schema(_conn)
    ensure_document_schema(_conn)
    ensure_supplier_master_schema(_conn)
    ensure_scorecard_schema(_conn)
    ensure_quality_schema(_conn)
    ensure_batch_aging_schema(_conn)
    ensure_reservation_schema(_conn)
    ensure_storage_control_schema(_conn)
    ensure_transit_schema(_conn)
    ensure_receipt_cost_schema(_conn)
    ensure_notification_schema(_conn)
    return True
