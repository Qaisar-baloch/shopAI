import streamlit as st
import pandas as pd
from db import (
    init_db,
    all_customers,
    orders_by_customer,
    order_items_for,
)
from styles import inject_theme, page_header, sidebar_brand, footer

st.set_page_config(page_title="Customers · DukaanAI", page_icon="👥", layout="wide")
inject_theme()
sidebar_brand()
init_db()


@st.cache_data(ttl=30)
def cached_customers():
    return all_customers()


@st.cache_data(ttl=30)
def cached_customer_orders(customer):
    return orders_by_customer(customer)


@st.cache_data(ttl=30)
def cached_items(order_id):
    return order_items_for(order_id)


# ---------------------------------------------------------------
# Page header
# ---------------------------------------------------------------
page_header(
    "Know every regular",
    "CUSTOMER RELATIONSHIPS",
    "Keep customer details, order history, and repeat business in one calm workspace.",
)


customers = cached_customers()

if not customers:
    st.info(
        "No customers yet. Place an order from **💬 Customer Chat** "
        "(use a real name instead of 'Guest') and they'll show up here."
    )
    footer()
    st.stop()


# ---- KPIs ----
total_customers = len(customers)
total_revenue = sum(float(c["total_spent"] or 0) for c in customers)
total_orders_all = sum(int(c["order_count"] or 0) for c in customers)
avg_order_value = (
    round(total_revenue / total_orders_all, 2) if total_orders_all else 0.0
)

k1, k2, k3, k4 = st.columns(4)
k1.metric("Customers", total_customers)
k2.metric("Total Revenue", f"Rs.{total_revenue:,.0f}")
k3.metric("Total Orders", total_orders_all)
k4.metric("Avg Order Value", f"Rs.{avg_order_value:,.0f}")

st.divider()

# ---- Search ----
search = st.text_input("🔍 Search by customer name", value="", key="cust_search")
filtered = customers
if search.strip():
    q = search.strip().lower()
    filtered = [c for c in customers if q in (c["customer"] or "").lower()]

if not filtered:
    st.warning(f"No customers match '{search}'.")
    footer()
    st.stop()


# ---- Table ----
st.subheader(f"👤 Customers ({len(filtered)})")

rows = []
for c in filtered:
    rows.append({
        "Name": c["customer"],
        "Orders": int(c["order_count"] or 0),
        "Total Spent (Rs.)": float(c["total_spent"] or 0),
        "Last Order": (c["last_order"] or "")[:19],
    })

df = pd.DataFrame(rows)
st.dataframe(df, use_container_width=True, hide_index=True)

st.divider()

# ---- Detail drill-down ----
st.subheader("🔍 Customer Detail")

customer_names = [c["customer"] for c in filtered]
selected_name = st.selectbox(
    "Select a customer to view their order history",
    customer_names,
    key="cust_select",
)

if selected_name:
    orders = cached_customer_orders(selected_name)

    if not orders:
        st.caption("This customer has no orders.")
    else:
        total_spent = sum(float(o["total"] or 0) for o in orders)
        confirmed = [o for o in orders if o["status"] == "CONFIRMED"]
        pending = [o for o in orders if o["status"] == "PENDING"]

        c1, c2, c3 = st.columns(3)
        c1.metric("Total Orders", len(orders))
        c2.metric("Confirmed", len(confirmed))
        c3.metric("Pending", len(pending))

        st.markdown(f"**Total spent:** Rs.{total_spent:,.0f}")

        st.markdown("#### Order History")

        for order in orders:
            status_icon = {
                "PENDING": "🟡",
                "CONFIRMED": "🟢",
                "REJECTED": "🔴",
            }.get(order["status"], "⚪")

            with st.expander(
                f"{status_icon} **{order['order_code']}** — "
                f"Rs.{order['total']:.2f}  ·  {order['status']}  ·  "
                f"{order['created_at'][:19]}"
            ):
                items = cached_items(order["id"])
                if items:
                    for it in items:
                        st.markdown(
                            f"- {it['product_name']} — {it['quantity']} {it['unit']} "
                            f"× Rs.{it['unit_price']:.2f} = Rs.{it['line_total']:.2f}"
                        )
                    st.markdown(f"**Total:** Rs.{order['total']:.2f}")
                else:
                    st.caption("No items recorded.")

footer()
