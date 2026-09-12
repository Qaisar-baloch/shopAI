import streamlit as st
import pandas as pd
from db import (
    init_db,
    list_products,
    add_product,
    update_product,
    delete_product,
    get_product_by_id,
)
from styles import inject_theme, page_header, sidebar_brand, footer

st.set_page_config(page_title="Inventory · DukaanAI", page_icon="📦", layout="wide")
inject_theme()
sidebar_brand()
init_db()


@st.cache_data(ttl=15)
def cached_products():
    return list_products()


# ---------------------------------------------------------------
# Page header
# ---------------------------------------------------------------
page_header(
    "Know what is moving",
    "INVENTORY OPERATIONS",
    "Monitor stockouts, spot restock risk, and keep the product catalog ready for live customer demand.",
)


# ---------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------
tab_view, tab_add, tab_edit = st.tabs(["👁️ View Products", "➕ Add Product", "✏️ Edit / Delete"])


# ===============================================================
# TAB 1 — VIEW
# ===============================================================
with tab_view:
    products = cached_products()

    if not products:
        st.info("No products yet. Use the **➕ Add Product** tab to create your first one.")
    else:
        col1, col2, col3 = st.columns([3, 2, 2])
        with col1:
            search = st.text_input("🔍 Search by name or alias", value="", key="inv_search")
        with col2:
            units = sorted({p["unit"] for p in products})
            unit_filter = st.selectbox("Unit", ["All"] + units, index=0, key="inv_unit")
        with col3:
            status_filter = st.selectbox(
                "Status", ["All", "In Stock", "Low Stock", "Out of Stock"],
                index=0, key="inv_status",
            )

        filtered = products
        if search.strip():
            q = search.strip().lower()
            filtered = [
                p for p in filtered
                if q in p["name"].lower() or q in (p["aliases"] or "").lower()
            ]
        if unit_filter != "All":
            filtered = [p for p in filtered if p["unit"] == unit_filter]
        if status_filter == "In Stock":
            filtered = [p for p in filtered if float(p["current_stock"]) > float(p["min_stock"])]
        elif status_filter == "Low Stock":
            filtered = [
                p for p in filtered
                if 0 < float(p["current_stock"]) <= float(p["min_stock"])
            ]
        elif status_filter == "Out of Stock":
            filtered = [p for p in filtered if float(p["current_stock"]) <= 0]

        total_products = len(products)
        low_count = sum(
            1 for p in products
            if float(p["current_stock"]) <= float(p["min_stock"])
        )
        stock_value = sum(
            float(p["current_stock"]) * float(p["unit_price"]) for p in products
        )

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Total Products", total_products)
        k2.metric("Low / Out of Stock", low_count)
        k3.metric("Stock Value", f"Rs.{stock_value:,.0f}")
        k4.metric("Showing", len(filtered))

        st.divider()

        if not filtered:
            st.warning("No products match your filters.")
        else:
            rows = []
            for p in filtered:
                stock = float(p["current_stock"])
                minimum = float(p["min_stock"])
                if stock <= 0:
                    status = "🔴 Out"
                elif stock <= minimum:
                    status = "🟡 Low"
                else:
                    status = "🟢 OK"

                rows.append({
                    "Name": p["name"],
                    "Aliases": p["aliases"] or "—",
                    "Unit": p["unit"],
                    "Price (Rs.)": float(p["unit_price"]),
                    "Stock": stock,
                    "Min": minimum,
                    "Status": status,
                })

            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True)


# ===============================================================
# TAB 2 — ADD
# ===============================================================
with tab_add:
    st.subheader("➕ Add New Product")
    st.caption("Fields marked with * are required.")

    with st.form("add_product_form", clear_on_submit=True):
        col_a, col_b = st.columns(2)
        with col_a:
            name = st.text_input("Product name *", placeholder="e.g. Basmati Rice")
            aliases = st.text_input(
                "Aliases (comma-separated)",
                placeholder="e.g. rice, chawal
