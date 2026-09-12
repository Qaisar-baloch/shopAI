import streamlit as st
from db import (
    init_db,
    pending_orders,
    recent_orders,
    order_items_for,
    update_order_status,
)
from inventory import accept_order, reject_order

st.set_page_config(page_title="Orders · DukaanAI", page_icon="🧾", layout="wide")
init_db()


# ---- Cached helpers ----
@st.cache_data(ttl=10)
def cached_pending():
    return pending_orders()


@st.cache_data(ttl=10)
def cached_recent(limit=50):
    return recent_orders(limit)


@st.cache_data(ttl=10)
def cached_items(order_id):
    return order_items_for(order_id)


# ---- Page header ----
st.title("🧾 Orders")
st.caption("Review incoming orders — accept to confirm and deduct stock, or reject to cancel.")


# ================================================================
# SECTION 1 — Pending orders
# ================================================================
pending = cached_pending()

if pending:
    st.subheader(f"🔔 Pending Orders ({len(pending)})")
    st.caption("These orders are waiting for shopkeeper approval. Stock is NOT yet deducted.")

    for order in pending:
        items = cached_items(order["id"])

        with st.expander(
            f"**{order['order_code']}** — {order['customer']} — Rs.{order['total']:.2f}  ·  PENDING",
            expanded=True,
        ):
            st.markdown(f"**Placed:** {order['created_at'][:19]}")

            # Items table
            if items:
                st.markdown("**Items:**")
                for it in items:
                    st.markdown(
                        f"- {it['product_name']} — {it['quantity']} {it['unit']} "
                        f"× Rs.{it['unit_price']:.2f} = **Rs.{it['line_total']:.2f}**"
                    )
            else:
                st.caption("No items on this order.")

            st.markdown(f"### Total: Rs.{order['total']:.2f}")
            st.divider()

            col_a, col_b = st.columns(2)

            with col_a:
                if st.button(
                    "✅ Accept Order",
                    key=f"accept_{order['id']}",
                    use_container_width=True,
                    type="primary",
                ):
                    result = accept_order(order["id"])
                    if not result["ok"]:
                        st.error(f"Failed: {result['error']}")
                    else:
                        msg = "Order accepted. Stock deducted."
                        if result.get("warnings"):
                            msg += " Warnings: " + "; ".join(result["warnings"])
                        st.success(msg)
                        st.cache_data.clear()
                        st.rerun()

            with col_b:
                if st.button(
                    "❌ Reject Order",
                    key=f"reject_{order['id']}",
                    use_container_width=True,
                ):
                    result = reject_order(order["id"])
                    if result["ok"]:
                        st.warning("Order rejected. No stock changes.")
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(f"Failed: {result['error']}")

else:
    st.success("✅ No pending orders right now.")


st.divider()


# ================================================================
# SECTION 2 — Order history
# ================================================================
st.subheader("📜 Order History")

# ---- Filters row ----
col1, col2 = st.columns([2, 3])
with col1:
    status_filter = st.selectbox(
        "Filter by Status",
        ["All", "PENDING", "CONFIRMED", "REJECTED"],
        index=0,
    )
with col2:
    limit_choice = st.selectbox("Show orders", [10, 20, 50, 100], index=1)

# ---- Fetch + filter ----
all_orders = cached_recent(limit_choice)
if status_filter != "All":
    all_orders = [o for o in all_orders if o["status"] == status_filter]

# ---- Render ----
if not all_orders:
    st.info(f"No orders found (filter: {status_filter}).")
else:
    for order in all_orders:
        status_icon = {
            "PENDING": "🟡",
            "CONFIRMED": "🟢",
            "REJECTED": "🔴",
        }.get(order["status"], "⚪")

        with st.expander(
            f"{status_icon} **{order['order_code']}** — {order['customer']} — "
            f"Rs.{order['total']:.2f}  ·  {order['status']}"
        ):
            st.markdown(f"**Placed:** {order['created_at'][:19]}")

            items = cached_items(order["id"])
            if items:
                for it in items:
                    st.markdown(
                        f"- {it['product_name']} — {it['quantity']} {it['unit']} "
                        f"× Rs.{it['unit_price']:.2f} = Rs.{it['line_total']:.2f}"
                    )
                st.markdown(f"**Total:** Rs.{order['total']:.2f}")
            else:
                st.caption("No items.")

            # Allow re-accepting a REJECTED order, or re-confirming a PENDING one
            if order["status"] == "PENDING":
                c1, c2 = st.columns(2)
                with c1:
                    if st.button(
                        "✅ Accept",
                        key=f"hist_accept_{order['id']}",
                        use_container_width=True,
                    ):
                        accept_order(order["id"])
                        st.cache_data.clear()
                        st.rerun()
                with c2:
                    if st.button(
                        "❌ Reject",
                        key=f"hist_reject_{order['id']}",
                        use_container_width=True,
                    ):
                        reject_order(order["id"])
                        st.cache_data.clear()
                        st.rerun()
            elif order["status"] == "REJECTED":
                if st.button(
                    "🔄 Reopen as Pending",
                    key=f"reopen_{order['id']}",
                    use_container_width=True,
                ):
                    update_order_status(order["id"], "PENDING")
                    st.cache_data.clear()
                    st.rerun()
