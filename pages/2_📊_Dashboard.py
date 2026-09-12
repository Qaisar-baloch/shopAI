import streamlit as st
import pandas as pd
from db import (
    init_db,
    recent_orders,
    low_stock_products,
    sales_by_product,
    sales_by_day,
    dashboard_stats,
)
from restock_agent import recommend_restock, inventory_health
from styles import inject_theme, page_header, sidebar_brand, footer

st.set_page_config(page_title="Dashboard · DukaanAI", page_icon="📊", layout="wide")
inject_theme()
sidebar_brand()
init_db()


@st.cache_data(ttl=30)
def cached_recent_orders(limit=20):
    return recent_orders(limit)


@st.cache_data(ttl=30)
def cached_low_stock():
    return low_stock_products()


@st.cache_data(ttl=30)
def cached_sales_by_day(limit=7):
    return sales_by_day(limit)


@st.cache_data(ttl=30)
def cached_sales_by_product(limit=8):
    return sales_by_product(limit)


@st.cache_data(ttl=30)
def cached_dashboard_stats():
    return dashboard_stats()


@st.cache_data(ttl=60)
def cached_restock_recs():
    return recommend_restock(lookback_days=14)


@st.cache_data(ttl=60)
def cached_inventory_health():
    return inventory_health()


# ---------------------------------------------------------------
# Page header
# ---------------------------------------------------------------
page_header(
    "Your shop, in one clear view",
    "SHOP OVERVIEW",
    "See what needs attention, what is selling, and where your next decision is hiding.",
)


# ---- Sidebar ----
with st.sidebar:
    st.divider()
    st.subheader("🛠️ Demo Controls")
    if st.button("🔄 Reset Demo Data", use_container_width=True):
        from seed import seed
        seed()
        st.cache_data.clear()
        st.session_state.messages = []
        st.session_state.draft_items = []
        st.success("Demo data reset.")
        st.rerun()


health = cached_inventory_health()
stats = cached_dashboard_stats()

k1, k2, k3, k4 = st.columns(4)
k1.metric("Total Orders", stats["total_orders"])
k2.metric("Total Sales", f"Rs.{stats['total_sales']:,.0f}")
k3.metric("Low-Stock Items", f"{health['low']}/{health['total_products']}")
k4.metric("Stock Value", f"Rs.{health['total_stock_value']:,.0f}")

if stats.get("pending_count", 0) > 0:
    st.warning(
        f"🔔 {stats['pending_count']} pending order(s) — "
        f"go to the 🧾 Orders page to accept or reject."
    )

st.divider()

# ---- Restock ----
st.subheader("🧠 Restock Recommendation Agent")
st.caption("Based on last 14 days of sales + current stock vs. minimum stock.")

recs = cached_restock_recs()
if not recs:
    st.success("✅ All products are above minimum stock. No restock needed.")
else:
    df = pd.DataFrame(recs)
    df = df[
        [
            "priority",
            "name",
            "current_stock",
            "min_stock",
            "sold_last_14d",
            "avg_daily_sales",
            "suggested_reorder_qty",
            "unit",
            "estimated_cost",
        ]
    ]
    df.columns = [
        "Priority",
        "Product",
        "In Stock",
        "Min",
        "Sold (14d)",
        "Avg/Day",
        "Reorder Qty",
        "Unit",
        "Est. Cost (Rs.)",
    ]
    st.dataframe(df, use_container_width=True, hide_index=True)
    total_cost = sum(r["estimated_cost"] for r in recs)
    st.info(f"**Estimated total restock cost:** Rs.{total_cost:,.0f}")

st.divider()

# ---- Charts ----
col_a, col_b = st.columns(2)
with col_a:
    st.subheader("📈 Sales by Day")
    daily = cached_sales_by_day(7)
    if daily:
        df_day = pd.DataFrame(daily).set_index("day")
        st.bar_chart(df_day["revenue"])
    else:
        st.caption("No sales yet.")

with col_b:
    st.subheader("🏆 Best-Selling Products")
    best = cached_sales_by_product(8)
    if best:
        df_best = pd.DataFrame(best).set_index("product_name")
        st.bar_chart(df_best["total_qty"])
    else:
        st.caption("No sales yet.")

st.divider()

# ---- Recent orders ----
st.subheader("🧾 Recent Orders")
recent = cached_recent_orders(20)
if recent:
    columns_to_show = ["order_code", "customer", "total", "status", "created_at"]
    df_recent = pd.DataFrame(recent)[columns_to_show]
    df_recent.columns = [
        "Order Code",
        "Customer",
        "Total (Rs.)",
        "Status",
        "Created",
    ]
    st.dataframe(df_recent, use_container_width=True, hide_index=True)
else:
    st.caption("No orders yet.")

footer()
