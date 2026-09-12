import streamlit as st
import pandas as pd
from db import (
    init_db,
    get_conn,
    recent_orders,
    low_stock_products,
    sales_by_product,
    sales_by_day,
    dashboard_stats,
)
from agents import parse_order
from inventory import build_order_summary, execute_order
from restock_agent import recommend_restock, inventory_health

# ---------------------------------------------------------------
# Setup
# ---------------------------------------------------------------
st.set_page_config(page_title="DukaanAI", page_icon="🛒", layout="wide")
init_db()


# --- Auto-seed on first deploy (Streamlit Cloud starts with empty DB) ---
def _ensure_seeded():
    conn = get_conn()
    count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    conn.close()
    if count == 0:
        from seed import seed
        seed()


_ensure_seeded()


# ---------------------------------------------------------------
# Session state
# ---------------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = [{
        "role": "assistant",
        "content": (
            "Assalam-o-Alaikum! 👋 Main **DukaanAI** hoon.\n\n"
            "Apna order likhein — jaise *'2kg atta, 1 dozen eggs aur 2 doodh'*"
        )
    }]

if "pending_order" not in st.session_state:
    st.session_state.pending_order = None


# ---------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------
tab_customer, tab_shop = st.tabs(["💬 Customer Chat", "📊 Shopkeeper Dashboard"])


# ===============================================================
# TAB 1 — Customer Chat
# ===============================================================
with tab_customer:
    st.title("🛒 DukaanAI")
    st.caption("Autonomous AI Business Agent for Micro-Businesses")

    customer_name = st.text_input(
        "Your name (optional)",
        value=st.session_state.get("customer_name", "Guest"),
        key="customer_name"
    )

    # Sidebar (only on chat tab)
    with st.sidebar:
        st.header("📋 Recent Orders")
        orders = recent_orders(8)
        if not orders:
            st.caption("No orders yet. Try placing one!")
        else:
            for o in orders:
                st.markdown(
                    f"**{o['order_code']}**  \n"
                    f"_{o['customer']}_ — **Rs.{o['total']}**  \n"
                    f"<small>{o['created_at'][:19]}</small>",
                    unsafe_allow_html=True
                )
                st.divider()

        st.header("⚠️ Low Stock")
        lows = low_stock_products()
        if not lows:
            st.caption("All good 👍")
        else:
            for p in lows:
                st.markdown(
                    f"- **{p['name']}**: {p['current_stock']} {p['unit']} "
                    f"*(min {p['min_stock']})*"
                )

    # Render chat history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Pending order → confirm/cancel
    if st.session_state.pending_order:
        order = st.session_state.pending_order
        with st.chat_message("assistant"):
            st.markdown("**🧾 Order Summary**")
            for item in order["items"]:
                st.markdown(
                    f"- {item['product']} — {item['quantity']} {item['unit']} "
                    f"× Rs.{item['unit_price']} = **Rs.{item['line_total']}**"
                )
            st.markdown(f"### Total: Rs.{order['grand_total']}")

            if order["out_of_stock"]:
                st.warning("⚠️ Some items are unavailable:")
                for oos in order["out_of_stock"]:
                    st.markdown(f"- **{oos['product']}** — {oos['reason']}")
                    for alt in order["alternatives"].get(oos["product"], []):
                        st.markdown(
                            f"  ↳ Alternative: **{alt['product']}** "
                            f"({alt['stock_left']} {alt['unit']} @ Rs.{alt['unit_price']})"
                        )

            col1, col2 = st.columns(2)
            with col1:
                if st.button("✅ Place Order", use_container_width=True,
                             disabled=len(order["items"]) == 0):
                    result = execute_order(
                        order,
                        customer=st.session_state.get("customer_name", "Guest"),
                    )
                    if not result["ok"]:
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": f"⚠️ Order failed: {result['error']}",
                        })
                    else:
                        msg = (
                            f"✅ **Order Confirmed!**\n\n"
                            f"**Order ID:** `{result['order_code']}`\n\n"
                            f"**Total:** Rs.{result['total']}\n\n"
                            f"Shukriya! Aap ka order jald deliver hoga. 🙏"
                        )
                        if result.get("deduction_warnings"):
                            msg += "\n\n⚠️ Stock warnings:\n" + \
                                   "\n".join(f"- {w}" for w in result["deduction_warnings"])
                        st.session_state.messages.append({
                            "role": "assistant", "content": msg
                        })
                    st.session_state.pending_order = None
                    st.rerun()

            with col2:
                if st.button("❌ Cancel", use_container_width=True):
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": "Order cancelled. Kuch aur chahiye? 🙂",
                    })
                    st.session_state.pending_order = None
                    st.rerun()

    # Chat input
    user_msg = st.chat_input("Type your order...")
    if user_msg:
        st.session_state.messages.append({"role": "user", "content": user_msg})
        with st.chat_message("user"):
            st.markdown(user_msg)

        with st.chat_message("assistant"):
            with st.spinner("Samajh raha hoon..."):
                parsed = parse_order(user_msg)

            if "error" in parsed:
                reply = f"⚠️ Sorry, samajh nahi paya: {parsed['error']}"
                st.markdown(reply)
                st.session_state.messages.append({"role": "assistant", "content": reply})
            elif not parsed["items"]:
                unknown = ", ".join(parsed.get("unknown", [])) or "kuch bhi"
                reply = (
                    f"❓ Mujhe in products ke baare mein nahi pata: *{unknown}*.\n\n"
                    f"Available items: atta, rice, milk, eggs, sugar, oil, bread, tea."
                )
                st.markdown(reply)
                st.session_state.messages.append({"role": "assistant", "content": reply})
            else:
                summary = build_order_summary(parsed["items"])
                st.session_state.pending_order = summary
                if parsed["unknown"]:
                    st.info(f"Note: skipped unknown products → {parsed['unknown']}")
                st.rerun()


# ===============================================================
# TAB 2 — Shopkeeper Dashboard
# ===============================================================
with tab_shop:
    st.title("📊 Shopkeeper Dashboard")

    # --- Sidebar: Demo controls ---
    with st.sidebar:
        st.divider()
        st.subheader("🛠️ Demo Controls")
        if st.button("🔄 Reset Demo Data", use_container_width=True):
            from seed import seed
            seed()
            st.session_state.messages = [{
                "role": "assistant",
                "content": "🔄 Demo reset. Dukaan fresh hai! Apna order likhein."
            }]
            st.session_state.pending_order = None
            st.success("Demo data reset.")
            st.rerun()

    # --- KPI row ---
    health = inventory_health()
    stats = dashboard_stats()

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Orders", stats["total_orders"])
    k2.metric("Total Sales", f"Rs.{stats['total_sales']:,.0f}")
    k3.metric("Low-Stock Items", f"{health['low']}/{health['total_products']}")
    k4.metric("Stock Value", f"Rs.{health['total_stock_value']:,.0f}")

    st.divider()

    # --- Restock Recommendations ---
    st.subheader("🧠 Restock Recommendation Agent")
    st.caption("Based on last 14 days of sales + current stock vs. minimum stock.")

    recs = recommend_restock(lookback_days=14)
    if not recs:
        st.success("✅ All products are above minimum stock. No restock needed.")
    else:
        df = pd.DataFrame(recs)
        df = df[[
            "priority", "name", "current_stock", "min_stock",
            "sold_last_14d", "avg_daily_sales",
            "suggested_reorder_qty", "unit", "estimated_cost"
        ]]
        df.columns = [
            "Priority", "Product", "In Stock", "Min", "Sold (14d)",
            "Avg/Day", "Reorder Qty", "Unit", "Est. Cost (Rs.)"
        ]
        st.dataframe(df, use_container_width=True, hide_index=True)

        total_cost = sum(r["estimated_cost"] for r in recs)
        st.info(f"**Estimated total restock cost:** Rs.{total_cost:,.0f}")

    st.divider()

    # --- Sales analytics ---
    col_a, col_b = st.columns(2)

    with col_a:
        st.subheader("📈 Sales by Day")
        daily = sales_by_day(limit=14)
        if daily:
            df_day = pd.DataFrame(daily).set_index("day")
            st.bar_chart(df_day["revenue"])
        else:
            st.caption("No sales yet.")

    with col_b:
        st.subheader("🏆 Best-Selling Products")
        best = sales_by_product(limit=8)
        if best:
            df_best = pd.DataFrame(best).set_index("product_name")
            st.bar_chart(df_best["total_qty"])
        else:
            st.caption("No sales yet.")

    st.divider()

    # --- Recent orders table ---
    st.subheader("🧾 Recent Orders")
    recent = recent_orders(20)
    if recent:
        df_recent = pd.DataFrame(recent)[[
            "order_code", "customer", "total", "status", "created_at"
        ]]
        df_recent.columns = [
            "Order Code", "Customer", "Total (Rs.)", "Status", "Created"
        ]
        st.dataframe(df_recent, use_container_width=True, hide_index=True)
    else:
        st.caption("No orders yet.")