import streamlit as st
from db import (
    init_db,
    recent_orders,
    low_stock_products,
    find_product,
    get_product_by_id,
    list_products,
)
from agents import classify_message, generate_reply
from inventory import build_order_summary, execute_order
from styles import inject_theme, page_header, sidebar_brand, footer

st.set_page_config(page_title="Customer Chat · DukaanAI", page_icon="💬", layout="wide")
inject_theme()
sidebar_brand()
init_db()


@st.cache_data(ttl=30)
def cached_recent_orders(limit=8):
    return recent_orders(limit)


@st.cache_data(ttl=30)
def cached_low_stock():
    return low_stock_products()


@st.cache_data(ttl=30)
def cached_full_inventory():
    return [
        {
            "name": p["name"],
            "unit": p["unit"],
            "unit_price": float(p["unit_price"]),
            "stock": float(p["current_stock"]),
        }
        for p in list_products()
    ]


if "messages" not in st.session_state:
    st.session_state.messages = []
if "draft_items" not in st.session_state:
    st.session_state.draft_items = []
if "customer_name" not in st.session_state:
    st.session_state.customer_name = "Guest"
if "pending_spend_orders" not in st.session_state:
    st.session_state.pending_spend_orders = []


def _trim_messages():
    if len(st.session_state.messages) > 40:
        st.session_state.messages = st.session_state.messages[-40:]


def _add_to_draft(products):
    for p in products:
        if p["quantity"] <= 0:
            continue
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


page_header(
    "A better way to take orders",
    "CUSTOMER AI DESK",
    'Place an order or check product availability. Try: "2kg atta, 1 dozen eggs" or "Is 2 milk available?"',
)


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
                f"<small>{o['created_at'][:19]} · {o['status']}</small>",
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


for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])


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
                     disabled=len(summary["items"]) == 0, type="primary"):
            result = execute_order(
                summary,
                customer=st.session_state.get("customer_name", "Guest"),
            )
            if not result["ok"]:
                reply = f"Sorry, order place nahi ho paya: {result['error']}"
            else:
                reply = (
                    f"✅ Order bhej diya gaya hai!\n\n"
                    f"**Order ID:** `{result['order_code']}`  \n"
                    f"**Total:** Rs. {result['total']:.2f}  \n"
                    f"**Status:** PENDING — shopkeeper will confirm shortly.\n\n"
                    f"Shukriya! 🙏"
                )
            st.session_state.messages.append({"role": "assistant", "content": reply})
            st.session_state.draft_items = []
            st.session_state.pending_spend_orders = []
            st.cache_data.clear()
            _trim_messages()
            st.rerun()
    with col_b:
        if st.button("🗑️ Clear Draft", use_container_width=True):
            st.session_state.draft_items = []
            st.session_state.pending_spend_orders = []
            st.session_state.messages.append({
                "role": "assistant",
                "content": "Draft clear kar diya. Naya order bataiye.",
            })
            _trim_messages()
            st.rerun()
    with col_c:
        if st.button("❌ Cancel All", use_container_width=True):
            st.session_state.draft_items = []
            st.session_state.pending_spend_orders = []
            st.session_state.messages.append({
                "role": "assistant",
                "content": "Order cancel. Kuch aur chahiye? 🙂",
            })
            _trim_messages()
            st.rerun()


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
            spend_orders = parsed.get("spend_orders", [])
            mismatches = parsed.get("unit_mismatch", [])

            # ---- P1: unit mismatch (hard) ----
            if mismatches and not products:
                m = mismatches[0]
                real = find_product(m.get("product", ""))
                data = {
                    "mismatch": {
                        "product": m.get("product"),
                        "customer_said_unit": m.get("customer_said_unit"),
                        "catalog_unit": real["unit"] if real else "?",
                        "price_per_unit": float(real["unit_price"]) if real else 0,
                        "stock": float(real["current_stock"]) if real else 0,
                    }
                }
                reply = generate_reply(user_msg, "unit_mismatch", data, language)

            # ---- P2: over-stock check (any product) ----
            elif any(p.get("exceeds_stock") for p in products):
                bad = next(p for p in products if p.get("exceeds_stock"))
                data = {
                    "mismatch": {
                        "product": bad["product"],
                        "unit": bad["unit"],
                        "requested": bad["quantity"],
                        "stock": bad["stock_available"],
                    }
                }
                reply = generate_reply(user_msg, "stock_exceeded", data, language)

            # ---- P3: MIXED — products and/or spend orders ----
            elif products or spend_orders:
                added_items_payload = []
                if products:
                    _add_to_draft(products)
                    added_items_payload = [
                        {"name": p["product"], "qty": p["quantity"], "unit": p["unit"]}
                        for p in products
                    ]

                # Only actionable spend orders go into pending
                actionable_spend = [
                    s for s in spend_orders
                    if s.get("fulfilment") in ("fraction", "full_units_with_leftover")
                    and not s.get("exceeds_stock")
                ]
                st.session_state.pending_spend_orders = actionable_spend

                data = {
                    "added_items": added_items_payload,
                    "spend_orders": spend_orders,
                    "current_draft": [
                        {"name": d["product"], "qty": d["quantity"], "unit": d["unit"]}
                        for d in st.session_state.draft_items
                    ],
                    "draft_total": sum(
                        d["quantity"] * d["unit_price"]
                        for d in st.session_state.draft_items
                    ),
                }
                reply = generate_reply(user_msg, intent, data, language)

            # ---- P4: greeting ----
            elif intent == "greeting":
                reply = generate_reply(user_msg, intent, {"note": "customer greeted"}, language)

            # ---- P5: inventory query ----
            elif intent == "inventory_query":
                all_items = cached_full_inventory()
                in_stock = [it for it in all_items if it["stock"] > 0]
                data = {
                    "query_type": "full_inventory",
                    "all_items": in_stock,
                    "total_products": len(all_items),
                    "in_stock_count": len(in_stock),
                }
                reply = generate_reply(user_msg, intent, data, language)

            # ---- P6: single product query ----
            elif intent in ("product_query", "price_query"):
                all_items = cached_full_inventory()
                in_stock = [it for it in all_items if it["stock"] > 0]
                reply = generate_reply(user_msg, "inventory_query",
                                       {"all_items": in_stock}, language)

            # ---- P7: confirm ----
            elif intent == "confirm":
                pending = st.session_state.get("pending_spend_orders", [])
                if pending:
                    for s in pending:
                        _add_to_draft([{
                            "product": s["product"],
                            "product_id": s["product_id"],
                            "quantity": s["computed_quantity"],
                            "unit": s["unit"],
                            "unit_price": s["unit_price"],
                        }])
                    st.session_state.pending_spend_orders = []
                    reply = "Theek hai, add kar diya. Neeche Confirm Order button dabaiye."
                else:
                    reply = "Confirm karne ke liye neeche 'Confirm Order' button dabaiye. 🙂"

            # ---- P8: cancel ----
            elif intent == "cancel":
                st.session_state.draft_items = []
                st.session_state.pending_spend_orders = []
                reply = generate_reply(user_msg, intent, {"note": "order cancelled"}, language)

            # ---- P9: FALLBACK - never silent ----
            else:
                all_items = cached_full_inventory()
                in_stock = [it for it in all_items if it["stock"] > 0]
                unknown = parsed.get("unknown", [])
                if unknown:
                    reply = (
                        f"Sorry, ye products catalog mein nahi hain: {', '.join(unknown)}. "
                        f"Aap ye available items try kar sakte hain."
                    )
                else:
                    reply = generate_reply(user_msg, "inventory_query",
                                           {"all_items": in_stock}, language)

            # ---- Final safety: never empty ----
            if not reply or not reply.strip():
                reply = (
                    "Main samajh nahi paya — dobara likh dein? "
                    "Jaise: '2kg atta, 1 dozen eggs' ya 'stock me kia hai'."
                )

            st.markdown(reply)
            st.session_state.messages.append({"role": "assistant", "content": reply})
            _trim_messages()
            st.rerun()
