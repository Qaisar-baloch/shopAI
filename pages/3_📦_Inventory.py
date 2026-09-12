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

st.set_page_config(page_title="Inventory · DukaanAI", page_icon="📦", layout="wide")
init_db()


# ---------------------------------------------------------------
# Cached helpers
# ---------------------------------------------------------------
@st.cache_data(ttl=15)
def cached_products():
    return list_products()


# ---------------------------------------------------------------
# Page header
# ---------------------------------------------------------------
st.title("📦 Inventory Management")
st.caption("Add, edit, and manage your product catalog. Stock auto-syncs across the app.")


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
        # ---- Filters ----
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

        # ---- Apply filters ----
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

        # ---- KPI row ----
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

        # ---- Table ----
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
                placeholder="e.g. rice, chawal, basmati",
            )
            unit = st.selectbox(
                "Unit *",
                ["kg", "gram", "litre", "ml", "dozen", "piece", "packet"],
                index=0,
            )
        with col_b:
            unit_price = st.number_input(
                "Unit price (Rs.) *", min_value=0.0, step=1.0, value=100.0,
            )
            current_stock = st.number_input(
                "Current stock *", min_value=0.0, step=1.0, value=10.0,
            )
            min_stock = st.number_input(
                "Minimum stock threshold *", min_value=0.0, step=1.0, value=3.0,
            )

        submitted = st.form_submit_button("✅ Add Product", use_container_width=True)

        if submitted:
            if not name.strip():
                st.error("Product name is required.")
            else:
                try:
                    add_product(
                        name=name.strip(),
                        aliases=aliases.strip(),
                        unit=unit,
                        unit_price=float(unit_price),
                        current_stock=float(current_stock),
                        min_stock=float(min_stock),
                    )
                    st.success(f"✅ Added **{name}** to inventory.")
                    st.cache_data.clear()
                except Exception as e:
                    if "UNIQUE" in str(e).upper():
                        st.error(f"❌ A product named **{name}** already exists.")
                    else:
                        st.error(f"❌ Failed to add product: {e}")


# ===============================================================
# TAB 3 — EDIT / DELETE
# ===============================================================
with tab_edit:
    products = cached_products()

    if not products:
        st.info("No products to edit yet.")
    else:
        st.subheader("✏️ Edit or Delete a Product")

        # Build label map
        product_labels = {
            f"{p['name']}  ·  {p['unit']}  ·  Rs.{p['unit_price']}  ·  stock {p['current_stock']}": p
            for p in products
        }

        selected_label = st.selectbox(
            "Select a product",
            list(product_labels.keys()),
            key="edit_select",
        )
        selected = product_labels[selected_label]

        st.divider()

        with st.form("edit_product_form"):
            st.markdown(f"**Editing:** `{selected['name']}` (ID #{selected['id']})")

            col_a, col_b = st.columns(2)
            with col_a:
                e_name = st.text_input("Name", value=selected["name"])
                e_aliases = st.text_input("Aliases", value=selected["aliases"] or "")
                e_unit = st.selectbox(
                    "Unit",
                    ["kg", "gram", "litre", "ml", "dozen", "piece", "packet"],
                    index=(
                        ["kg", "gram", "litre", "ml", "dozen", "piece", "packet"]
                        .index(selected["unit"])
                        if selected["unit"] in ["kg", "gram", "litre", "ml", "dozen", "piece", "packet"]
                        else 0
                    ),
                )
            with col_b:
                e_price = st.number_input(
                    "Unit price (Rs.)",
                    min_value=0.0, step=1.0,
                    value=float(selected["unit_price"]),
                )
                e_stock = st.number_input(
                    "Current stock",
                    min_value=0.0, step=1.0,
                    value=float(selected["current_stock"]),
                )
                e_min = st.number_input(
                    "Minimum stock",
                    min_value=0.0, step=1.0,
                    value=float(selected["min_stock"]),
                )

            col_save, col_delete = st.columns(2)
            with col_save:
                save_clicked = st.form_submit_button(
                    "💾 Save Changes", use_container_width=True, type="primary",
                )
            with col_delete:
                delete_clicked = st.form_submit_button(
                    "🗑️ Delete Product", use_container_width=True,
                )

            if save_clicked:
                try:
                    update_product(
                        pid=selected["id"],
                        name=e_name.strip(),
                        aliases=e_aliases.strip(),
                        unit=e_unit,
                        unit_price=float(e_price),
                        current_stock=float(e_stock),
                        min_stock=float(e_min),
                    )
                    st.success(f"✅ Updated **{e_name}**.")
                    st.cache_data.clear()
                    st.rerun()
                except Exception as e:
                    if "UNIQUE" in str(e).upper():
                        st.error(f"❌ Another product already uses the name **{e_name}**.")
                    else:
                        st.error(f"❌ Failed to update: {e}")

            if delete_clicked:
                try:
                    delete_product(selected["id"])
                    st.success(f"🗑️ Deleted **{selected['name']}**.")
                    st.cache_data.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Failed to delete: {e}")
