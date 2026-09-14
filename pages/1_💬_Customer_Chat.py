import re as _re
import streamlit as st
from db import (
    init_db, recent_orders, low_stock_products,
    find_product, get_product_by_id, list_products,
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
        {"name": p["name"], "unit": p["unit"],
         "unit_price": float(p["unit_price"]),
         "stock": float(p["current_stock"])}
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


def _base_name(product_name):
    cleaned = _re.sub(r"\s*\d+.*$", "", product_name).strip().lower()
    return cleaned or product_name.lower().split()[0]


def _add_to_draft(products):
    """Replace by base name: adding 'Atta 10kg' replaces 'Atta 5kg'."""
    for p in products:
        if p["quantity"] <= 0:
            continue
        base = _base_name(p["product"])
        st.session_state.draft_items = [
            d for d in st.session_state.draft_items
            if _base_name(d["product"]) != base
        ]
        st.session_state.draft_items.append({
            "product": p["product"], "product_id": p["product_id"],
            "quantity": p["quantity"], "unit": p["unit"],
            "unit_price": p["unit_price"],
        })


def _draft_summary():
    items_with_ids = [
        {"product": d["product"], "product_id": d["product_id"],
         "quantity": d["quantity"], "unit": d["unit"],
         "unit_price": d["unit_price"]}
        for d in st.session_state.draft_items
    ]
    return build_order_summary(items_with_ids)


page_header(
    "A better way to take orders",
    "CUSTOMER AI DESK",
    'Try: "5kg atta" or "1 dozen eggs". The AI will ask if a unit is unclear.',
)


with st.sidebar:
    st.header("📋 Recent Orders")
    orders = cached_recent_orders(8)
    if not orders:
        st.caption("No orders yet.")
    else:
        for o in orders:
            st.markdown(
                f"**{o['order_code']}**  \n_{o['customer']}_ — **Rs.{o['total']}**  \n"
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
            st.markdown(f"- **{p['name']}**: {p['current_stock']} {p['unit']}")


for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])


if st.session_state.draft_items:
    st.divider()
    st.subheader("🧾 Order Draft (not final yet)")
    summary = _draft_summary()
    for it in summary["items"]:
        c1, c2, c3 = st.columns([3, 3, 2])
        with c1:
            st.markdown(f"✅ **{it['product']}** — {it['quantity']} {it['unit']}")
        with c2:
            st.markdown(f"Rs. {it['unit_price']:.2f} × {it['quantity']} = **Rs. {it['line_total']:.2f}**")
        with c3:
            st.markdown("*In stock*")
    for oos in summary["out_of_stock"]:
        st.warning(f"⚠️ {oos['product']} — {oos['reason']}")
    st.markdown(f"### Total: Rs. {summary['grand_total']:.2f}")

    c_a, c_b, c_c = st.columns(3)
    with c_a:
        if st.button("✅ Confirm Order", use_container_width=True,
                     disabled=len(summary["items"]) == 0, type="primary"):
            result = execute_order(summary, customer=st.session_state.get("customer_name", "Guest"))
            if not result["ok"]:
                reply = f"Order fail: {result['error']}"
            else:
                reply = (
                    f"✅ Order confirmed!\n\n"
                    f"**Order ID:** `{result['order_code']}`  \n"
                    f"**Total:** Rs. {result['total']:.2f}  \n"
                    f"**Status:** PENDING\n\nShukriya! 🙏"
                )
            st.session_state.messages.append({"role": "assistant", "content": reply})
            st.session_state.draft_items = []
            st.session_state.pending_spend_orders = []
            st.cache_data.clear()
            _trim_messages()
            st.rerun()
    with c_b:
        if st.button("🗑️ Clear Draft", use_container_width=True):
            st.session_state.draft_items = []
            st.session_state.pending_spend_orders = []
            st.session_state.messages.append({"role": "assistant", "content": "Draft clear."})
            _trim_messages()
            st.rerun()
    with c_c:
        if st.button("❌ Cancel All", use_container_width=True):
            st.session_state.draft_items = []
            st.session_state.pending_spend_orders = []
            st.session_state.messages.append({"role": "assistant", "content": "Cancelled."})
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
            ambiguous = parsed.get("ambiguous", [])
            spend_orders = parsed.get("spend_orders", [])
            mismatches = parsed.get("unit_mismatch", [])
            rate_limit = parsed.get("_rate_limit")   # set by classifier if Groq failed

            # P1: explicit rate-limit — say so honestly, no fake reply
            if rate_limit and rate_limit.get("kind") == "rate_limit":
                wait_txt = ""
                if rate_limit.get("retry_seconds"):
                    mins = max(1, rate_limit["retry_seconds"] // 60)
                    wait_txt = f" ({mins} min baad try karein)" if language == "ur_roman" \
                               else f" (~{mins} min)"
                reply = (
                    f"⚠️ AI service ka daily limit khatam ho gaya hai{wait_txt}.\n\n"
                    f"Filhal simple orders **offline** handle ho rahe hain:\n"
                    f"- `2kg atta`\n- `1 dozen eggs`\n- `100 ka tel`\n\n"
                    f"Ye try karein."
                    if language in ("ur_roman", "ur") else
                    f"⚠️ The AI service has reached its daily limit{wait_txt}.\n\n"
                    f"Simple orders are still handled offline:\n"
                    f"- `2kg atta`\n- `1 dozen eggs`\n- `100 ka tel`\n\n"
                    f"Give these a try."
                )

            # P2: unit mismatch
            elif mismatches and not products:
                m = mismatches[0]
                real = find_product(m.get("product", ""))
                data = {"mismatch": {
                    "product": m.get("product"),
                    "catalog_unit": real["unit"] if real else "?",
                    "price_per_unit": float(real["unit_price"]) if real else 0,
                }}
                reply = generate_reply(user_msg, "unit_mismatch", data, language)

            # P3: over-stock
            elif any(p.get("exceeds_stock") for p in products):
                bad = next(p for p in products if p.get("exceeds_stock"))
                reply = (
                    f"Sirf {bad['stock_available']} {bad['unit']} {bad['product']} bacha hai. "
                    f"Aap ne {bad['quantity']} maanga. Kitna lena chahenge?"
                )

            # P4: products and/or spend orders and/or ambiguous
            elif products or spend_orders or ambiguous:
                added_items_payload = []
                if products:
                    _add_to_draft(products)
                    added_items_payload = [
                        {"name": p["product"], "qty": p["quantity"], "unit": p["unit"]}
                        for p in products
                    ]
                actionable_spend = [
                    s for s in spend_orders
                    if s.get("fulfilment") in ("fraction", "full_units_with_leftover")
                    and not s.get("exceeds_stock")
                ]
                st.session_state.pending_spend_orders = actionable_spend
                data = {
                    "added_items": added_items_payload,
                    "spend_orders": spend_orders,
                    "ambiguous": ambiguous,
                    "draft_total": sum(d["quantity"] * d["unit_price"]
                                       for d in st.session_state.draft_items),
                }
                reply = generate_reply(user_msg, intent, data, language)

            elif intent == "greeting":
                reply = generate_reply(user_msg, intent, {"note": "greeted"}, language)

            elif intent == "inventory_query":
                all_items = cached_full_inventory()
                in_stock = [it for it in all_items if it["stock"] > 0]
                reply = generate_reply(user_msg, intent, {"all_items": in_stock}, language)

            elif intent in ("product_query", "price_query"):
                all_items = cached_full_inventory()
                in_stock = [it for it in all_items if it["stock"] > 0]
                reply = generate_reply(user_msg, "inventory_query",
                                       {"all_items": in_stock}, language)

            elif intent == "confirm":
                pending = st.session_state.get("pending_spend_orders", [])
                if pending:
                    for s in pending:
                        _add_to_draft([{
                            "product": s["product"], "product_id": s["product_id"],
                            "quantity": s["computed_quantity"], "unit": s["unit"],
                            "unit_price": s["unit_price"],
                        }])
                    st.session_state.pending_spend_orders = []
                    reply = "Theek hai, add kar diya. Neeche Confirm Order dabaiye."
                else:
                    reply = "Neeche 'Confirm Order' button dabaiye. 🙂"

            elif intent == "cancel":
                st.session_state.draft_items = []
                st.session_state.pending_spend_orders = []
                reply = "Cancel kar diya."

            else:
                unknown = parsed.get("unknown", [])
                if unknown:
                    reply = f"Ye products nahi hain: {', '.join(unknown)}. Try: atta, chawal, doodh, anday, cheeni, tel."
                else:
                    reply = (
                        "Main samajh nahi paya. Try:\n"
                        "- Order: `5kg atta, 1 dozen eggs`\n"
                        "- Price: `atta ka rate`\n"
                        "- Stock: `stock me kia hai`"
                    )

            if not reply or not reply.strip():
                reply = "Dobara likh dein? Jaise: `5kg atta`."

            st.markdown(reply)
            st.session_state.messages.append({"role": "assistant", "content": reply})
            _trim_messages()
            st.rerun()
