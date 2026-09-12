import streamlit as st
import pandas as pd
from db import (
    init_db, get_conn, recent_orders, low_stock_products,
    sales_by_product, sales_by_day, dashboard_stats,
    find_product, get_product_by_id,
)
from agents import classify_message, generate_reply
from inventory import build_order_summary, execute_order
from restock_agent import recommend_restock, inventory_health

# ---------------------------------------------------------------
# Setup
# ---------------------------------------------------------------
st.set_page_config(page_title="DukaanAI", page_icon="🛒", layout="wide")
init_db()


def _ensure_seeded():
    conn = get_conn()
    count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    conn.close()
    if count == 0:
        from seed import seed
        seed()


_ensure_seeded()


# ---------------------------------------------------------------
# Cached data helpers
# ---------------------------------------------------------------
@st.cache_data(ttl=30)
def cached_recent_orders(limit=8):
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
# Session state
# ---------------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []

if "draft_items" not in st.session_state:
    st.session_state.draft_items = []   # list of dicts: {product, product_id, quantity, unit, unit_price}

if "customer_name" not in st.session_state:
    st.session_state.customer_name = "Guest"


def _trim_messages():
    if len(st.session_state.messages) > 30:
        st.session_state.messages = st.session_state.messages[-30:]


def _add_to_draft(products):
    """Merge new parsed products into the draft order."""
    for p in products:
        if p["quantity"] <= 0:
            continue
        # If same product already in draft, sum quantity
        existing = next(
            (d for d in st.session_state.draft_items if d["product_id"] == p["product_id"]),
            None,
        )
        if existing:
            existing["quantity"] += p["quantity"]
        else:
            st.session_state.draft_items.append({
                "product": p["product"],
                "product_id": p["product_id"],
                "quantity": p["quantity"],
                "unit": p["unit"],
                "unit_price": p["unit_price"],
            })


def _draft_summary():
    """Return a build_order_summary-compatible dict from draft items."""
    items_with_ids = [
        {
            "product": d["product"],
            "product_id": d["product_id"],
            "quantity": d["quantity"],
            "unit": d["unit"],
            "unit_price": d["unit_price"],
        }
        for d in st.session_state.draft_items
    ]
    return build_order_summary(items_with_ids)


# ---------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------
tab_customer, tab_shop = st.tabs(["💬 Customer Chat", "📊 Shopkeeper Dashboard"])


# ===============================================================
# TAB 1 — Customer Chat
# ===============================================================
with tab_customer:
    st.title("💬 Customer Chat")
    st.caption(
        'Type an order the way a customer would — English, Urdu, or Roman Urdu. '
        'e.g. "2kg atta, 1 dozen eggs aur 2 doodh"'
    )

    # Sidebar
    with st.sidebar:
        st.header("📋 Recent Orders")
        orders = cached_recent_orders(8)
        if not orders:
            st.caption("No orders yet. Try placing one!")
        else:
            for o in orders:
                st.markdown(
                    f"**{o['order_code']}**  \n"
                    f"_{o['customer']}_ — **Rs.{o['total']}**  \n"
                    f"<small>{o['created_at'][:19]}</small>",
                    unsafe_allow_html=True,
                )
                st.divider()

        st.header("⚠️ Low Stock")
        lows = cached_low_stock()
        if not lows:
            st.caption("All good 👍")
        else:
            for p in lows:
                st.markdown(
                    f"- **{p['name']}**: {p['current_stock']} {p['unit']} "
                    f"*(min {p['min_stock']})*"
                )

    # Chat history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # ------- Order Draft panel -------
    if st.session_state.draft_items:
        st.divider()
        st.subheader("🧾 Order Draft (from live inventory — not final yet)")

        summary = _draft_summary()

        for it in summary["items"]:
            col1, col2, col3 = st.columns([3, 3, 2])
            with col1:
                st.markdown(f"✅ **{it['product']}** — {it['quantity']} {it['unit']}")
            with col2:
                st.markdown(
                    f"Rs. {it['unit_price']:.2f} × {it['quantity']} = **Rs. {it['line_total']:.2f}**"
                )
            with col3:
                st.markdown("*In stock*")

        for oos in summary["out_of_stock"]:
            st.warning(f"⚠️ {oos['product']} — {oos['reason']}")
            for alt in summary["alternatives"].get(oos["product"], []):
                st.caption(
                    f"↳ Try **{alt['product']}** — {alt['stock_left']} {alt['unit']} @ Rs.{alt['unit_price']}"
                )

        st.markdown(f"### Total: Rs. {summary['grand_total']:.2f}")

        col_a, col_b, col_c = st.columns(3)
        with col_a:
            if st.button("✅ Confirm Order", use_container_width=True,
                         disabled=len(summary["items"]) == 0):
                result = execute_order(
                    summary,
                    customer=st.session_state.get("customer_name", "Guest"),
                )
                if not result["ok"]:
                    reply = f"Sorry, order place nahi ho paya: {result['error']}"
                else:
                    reply = (
                        f"✅ Order confirm ho gaya!\n\n"
                        f"**Order ID:** `{result['order_code']}`  \n"
                        f"**Total:** Rs. {result['total']:.2f}\n\n"
                        f"Shukriya! Aap ka order jald deliver hoga."
                    )
                st.session_state.messages.append({"role": "assistant", "content": reply})
                st.session_state.draft_items = []
                st.cache_data.clear()
                _trim_messages()
                st.rerun()
        with col_b:
            if st.button("🗑️ Clear Draft", use_container_width=True):
                st.session_state.draft_items = []
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": "Draft clear kar diya. Naya order bataiye.",
                })
                _trim_messages()
                st.rerun()
        with col_c:
            if st.button("❌ Cancel All", use_container_width=True):
                st.session_state.draft_items = []
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": "Order cancel. Kuch aur chahiye? 🙂",
                })
                _trim_messages()
                st.rerun()

    # ------- Chat input -------
    user_msg = st.chat_input("Type your order...")
    if user_msg:
        st.session_state.messages.append({"role": "user", "content": user_msg})
        with st.chat_message("user"):
            st.markdown(user_msg)

        with st.chat_message("assistant"):
            with st.spinner("Ek second..."):
                parsed = classify_message(user_msg)
                intent = parsed.get("intent", "other")
                language = parsed.get("language", "en")
                products = parsed.get("products", [])

                # ------ Greeting ------
                if intent == "greeting":
                    data = {"note": "customer greeted"}
                    reply = generate_reply(user_msg, intent, data, language)

                # ------ Product query (availability / price / stock) ------
                elif intent == "product_query":
                    if products:
                        p = products[0]
                        real = get_product_by_id(p["product_id"])
                        data = {
                            "product": {
                                "name": real["name"],
                                "unit": real["unit"],
                                "unit_price": real["unit_price"],
                                "stock": real["current_stock"],
                            }
                        }
                        reply = generate_reply(user_msg, intent, data, language)
                    else:
                        reply = generate_reply(user_msg, intent,
                                               {"note": "product not in catalog"}, language)

                # ------ Order intent ------
                elif intent == "order_intent":
                    if products:
                        _add_to_draft(products)
                        draft = st.session_state.draft_items
                        items_for_reply = [
                            {"name": d["product"], "qty": d["quantity"], "unit": d["unit"]}
                            for d in draft
                        ]
                        total = sum(d["quantity"] * d["unit_price"] for d in draft)
                        data = {
                            "added_items": [
                                {"name": p["product"], "qty": p["quantity"], "unit": p["unit"]}
                                for p in products
                            ],
                            "current_draft": items_for_reply,
                            "draft_total": total,
                        }
                        reply = generate_reply(user_msg, intent, data, language)
                    else:
                        reply = "Koi product samajh nahi aaya — dobara likh dein?"

                # ------ Confirm / Cancel ------
                elif intent == "confirm":
                    reply = "Confirm karne ke liye neeche 'Confirm Order' button dabaiye. 🙂"
                elif intent == "cancel":
                    st.session_state.draft_items = []
                    reply = generate_reply(user_msg, intent, {"note": "order cancelled"}, language)

                # ------ Fallback ------
                else:
                    reply = generate_reply(user_msg, intent, {"note": "could not classify"}, language)

                st.markdown(reply)
                st.session_state.messages.append({"role": "assistant", "content": reply})
                _trim_messages()
                st.rerun()


# ===============================================================
# TAB 2 — Shopkeeper Dashboard
# ===============================================================
with tab_shop:
    st.title("📊 Shopkeeper Dashboard")

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

    st.divider()

    st.subheader("🧠 Restock Recommendation Agent")
    st.caption("Based on last 14 days of sales + current stock vs. minimum stock.")

    recs = cached_restock_recs()
    if not recs:
        st.success("✅ All products are above minimum stock. No restock needed.")
    else:
        df = pd.DataFrame(recs)
        df = df[[
            "priority", "name", "current_stock", "min_stock",
            "sold_last_14d", "avg_daily_sales",
            "suggested_reorder_qty", "unit", "estimated_cost",
        ]]
        df.columns = [
            "Priority", "Product", "In Stock", "Min", "Sold (14d)",
            "Avg/Day", "Reorder Qty", "Unit", "Est. Cost (Rs.)",
        ]
        st.dataframe(df, use_container_width=True, hide_index=True)
        total_cost = sum(r["estimated_cost"] for r in recs)
        st.info(f"**Estimated total restock cost:** Rs.{total_cost:,.0f}")

    st.divider()

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

    st.subheader("🧾 Recent Orders")
    recent = cached_recent_orders(20)
    if recent:
        df_recent = pd.DataFrame(recent)[[
            "order_code", "customer", "total", "status", "created_at",
        ]]
        df_recent.columns = [
            "Order Code", "Customer", "Total (Rs.)", "Status", "Created",
        ]
        st.dataframe(df_recent, use_container_width=True, hide_index=True)
    else:
        st.caption("No orders yet.")
