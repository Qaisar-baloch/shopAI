import re as _re
import streamlit as st
from db import init_db, recent_orders, low_stock_products, find_product, list_products
from agents import classify_message, generate_reply, resolve_pending_selection
from chat_fixes import smart_classify_message
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
    return [{"name": p["name"], "unit": p["unit"], "unit_price": float(p["unit_price"]), "stock": float(p["current_stock"])} for p in list_products()]


if "messages" not in st.session_state:
    st.session_state.messages = []
if "draft_items" not in st.session_state:
    st.session_state.draft_items = []
if "customer_name" not in st.session_state:
    st.session_state.customer_name = "Guest"
if "pending_spend_orders" not in st.session_state:
    st.session_state.pending_spend_orders = []
if "pending_ambiguity" not in st.session_state:
    st.session_state.pending_ambiguity = []


def _trim_messages():
    if len(st.session_state.messages) > 40:
        st.session_state.messages = st.session_state.messages[-40:]


def _base_name(product_name):
    cleaned = _re.sub(r"\s*\d+(?:\.\d+)?\s*.*$", "", product_name).strip().lower()
    return cleaned or product_name.lower().split()[0]


def _add_to_draft(products):
    # Same product/SKU is merged; choosing a different size replaces the
    # previous size in that product family, which is what the chat wording implies.
    for p in products:
        if float(p.get("quantity", 0)) <= 0:
            continue
        base = _base_name(p["product"])
        st.session_state.draft_items = [d for d in st.session_state.draft_items if _base_name(d["product"]) != base]
        st.session_state.draft_items.append({
            "product": p["product"], "product_id": p["product_id"], "quantity": p["quantity"],
            "unit": p["unit"], "unit_price": p["unit_price"],
        })


def _draft_summary():
    return build_order_summary([
        {"product": d["product"], "product_id": d["product_id"], "quantity": d["quantity"], "unit": d["unit"], "unit_price": d["unit_price"]}
        for d in st.session_state.draft_items
    ])


page_header(
    "A better way to take orders",
    "CUSTOMER AI DESK",
    'Try: "5kg atta" · "1 dozen eggs" · "5kg wala kar do"',
)

with st.sidebar:
    st.header("📋 Recent Orders")
    orders = cached_recent_orders(8)
    if not orders:
        st.caption("No orders yet.")
    else:
        for o in orders:
            st.markdown(f"**{o['order_code']}**  \n_{o['customer']}_ — **Rs.{o['total']}**  \n<small>{o['created_at'][:19]} · {o['status']}</small>", unsafe_allow_html=True)
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

if st.session_state.pending_ambiguity:
    st.info("💡 Size select karein — jaise **5kg wala**, **10kg wala**, ya **pehla wala**.")

if st.session_state.draft_items:
    st.divider()
    st.subheader("🧾 Order Draft")
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
        if st.button("✅ Confirm Order", use_container_width=True, disabled=len(summary["items"]) == 0, type="primary"):
            result = execute_order(summary, customer=st.session_state.get("customer_name", "Guest"))
            reply = (f"Order failed: {result['error']}" if not result["ok"] else
                     f"✅ Order confirmed!\n\n**Order ID:** `{result['order_code']}`  \n**Total:** Rs. {result['total']:.2f}  \n**Status:** PENDING\n\nShukriya! 🙏")
            st.session_state.messages.append({"role": "assistant", "content": reply})
            st.session_state.draft_items = []
            st.session_state.pending_spend_orders = []
            st.session_state.pending_ambiguity = []
            st.cache_data.clear()
            _trim_messages()
            st.rerun()
    with c_b:
        if st.button("🗑️ Clear Draft", use_container_width=True):
            st.session_state.draft_items = []
            st.session_state.pending_spend_orders = []
            st.session_state.pending_ambiguity = []
            st.session_state.messages.append({"role": "assistant", "content": "Draft clear."})
            _trim_messages()
            st.rerun()
    with c_c:
        if st.button("❌ Cancel All", use_container_width=True):
            st.session_state.draft_items = []
            st.session_state.pending_spend_orders = []
            st.session_state.pending_ambiguity = []
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
            # Conversation memory: if the previous turn asked "which size?",
            # resolve natural follow-ups such as "5kg wala kar do" locally.
            selected = resolve_pending_selection(user_msg, st.session_state.pending_ambiguity)
            if selected:
                st.session_state.pending_ambiguity = []
                parsed = {
                    "intent": "order_intent", "language": "ur_roman",
                    "products": [selected], "ambiguous": [], "spend_orders": [],
                    "unit_mismatch": [], "unknown": [], "_source": "selection",
                }
            else:
                parsed = smart_classify_message(user_msg, classify_message)

            intent = parsed.get("intent", "other")
            language = parsed.get("language", "en")
            products = parsed.get("products", [])
            ambiguous = parsed.get("ambiguous", [])
            spend_orders = parsed.get("spend_orders", [])
            mismatches = parsed.get("unit_mismatch", [])
            rate_limit = parsed.get("_rate_limit")

            if ambiguous:
                # Keep the options alive for the next customer turn.
                st.session_state.pending_ambiguity = ambiguous

            if rate_limit and rate_limit.get("kind") == "rate_limit":
                reply = ("⚠️ AI service ka daily limit khatam ho gaya hai. Simple orders abhi bhi locally handle ho rahe hain: `5kg atta`, `1 dozen eggs`." if language in ("ur_roman", "ur") else "⚠️ The AI service has reached its daily limit. Simple orders are still handled locally: `5kg atta`, `1 dozen eggs`.")
            elif mismatches and not products:
                m = mismatches[0]
                real = find_product(m.get("product", ""))
                reply = generate_reply(user_msg, "unit_mismatch", {"mismatch": {"product": m.get("product"), "catalog_unit": real["unit"] if real else "?", "price_per_unit": float(real["unit_price"]) if real else 0}}, language)
            elif any(p.get("exceeds_stock") for p in products):
                bad = next(p for p in products if p.get("exceeds_stock"))
                reply = f"Sirf {bad['stock_available']} {bad['unit']} {bad['product']} bacha hai. Aap ne {bad['quantity']} maanga. Kitna lena chahenge?"
            elif products or spend_orders or ambiguous:
                added = []
                if products:
                    _add_to_draft(products)
                    added = [{"name": p["product"], "qty": p["quantity"], "unit": p["unit"]} for p in products]
                actionable = [s for s in spend_orders if s.get("fulfilment") in ("fraction", "full_units_with_leftover") and not s.get("exceeds_stock")]
                st.session_state.pending_spend_orders = actionable
                draft_total = sum(float(d["quantity"]) * float(d["unit_price"]) for d in st.session_state.draft_items)
                reply = generate_reply(user_msg, "ambiguous_request" if ambiguous and not added else "order_intent", {"added_items": added, "ambiguous": ambiguous, "spend_orders": spend_orders, "draft_total": draft_total}, language)
            elif intent == "greeting":
                reply = generate_reply(user_msg, intent, {"note": "greeted"}, language)
            elif intent == "inventory_query":
                in_stock = [it for it in cached_full_inventory() if it["stock"] > 0]
                reply = generate_reply(user_msg, intent, {"all_items": in_stock}, language)
            elif intent == "product_query":
                all_items = cached_full_inventory()
                query_items = parsed.get("query_items")
                if query_items:
                    wanted = {p["id"] for p in query_items}
                    in_stock = [it for it, p in zip(all_items, list_products()) if p["id"] in wanted and it["stock"] > 0]
                    if not in_stock:
                        in_stock = [it for it, p in zip(all_items, list_products()) if p["id"] in wanted]
                else:
                    in_stock = [it for it in all_items if it["stock"] > 0]
                reply = generate_reply(user_msg, "product_query", {"all_items": in_stock}, language)
            elif intent == "confirm":
                pending = st.session_state.get("pending_spend_orders", [])
                if pending:
                    for s in pending:
                        _add_to_draft({"product": s["product"], "product_id": s["product_id"], "quantity": s["computed_quantity"], "unit": s["unit"], "unit_price": s["unit_price"]})
                    st.session_state.pending_spend_orders = []
                    reply = "Theek hai, add kar diya. Neeche Confirm Order dabaiye."
                else:
                    reply = "Neeche Confirm Order dabaiye. 🙂"
            elif intent == "cancel":
                st.session_state.draft_items = []
                st.session_state.pending_spend_orders = []
                st.session_state.pending_ambiguity = []
                reply = "Cancel kar diya."
            else:
                unknown = parsed.get("unknown", [])
                reply = (f"Ye product catalog mein nahi hai: {', '.join(unknown)}." if unknown else "Main samajh nahi paya. Try: `5kg atta`, `1 dozen eggs`, `sugar ka rate`, ya `stock me kia kia hai`.")

            if not reply or not reply.strip():
                reply = "Dobara likh dein? Jaise: `5kg atta`."
            st.markdown(reply)
            st.session_state.messages.append({"role": "assistant", "content": reply})
            _trim_messages()
            st.rerun()

footer()
