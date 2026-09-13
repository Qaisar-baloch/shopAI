import os
import json
import time
import re
import functools
from groq import Groq
from db import find_product, list_products, get_product_by_id


@functools.lru_cache(maxsize=1)
def get_client():
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        try:
            import streamlit as st
            api_key = st.secrets.get("GROQ_API_KEY")
        except Exception:
            pass
    if not api_key:
        secrets_path = os.path.join(".streamlit", "secrets.toml")
        if os.path.exists(secrets_path):
            try:
                import tomllib
                with open(secrets_path, "rb") as f:
                    text = f.read().decode("utf-8-sig")
                api_key = tomllib.loads(text).get("GROQ_API_KEY")
            except ModuleNotFoundError:
                try:
                    import tomli
                    with open(secrets_path, "rb") as f:
                        text = f.read().decode("utf-8-sig")
                    api_key = tomli.loads(text).get("GROQ_API_KEY")
                except Exception:
                    pass
            except Exception:
                pass
    if not api_key or not str(api_key).startswith("gsk_"):
        raise ValueError(
            "GROQ_API_KEY not found or invalid.\n"
            'Set it in .streamlit/secrets.toml as: GROQ_API_KEY = "gsk_..."'
        )
    return Groq(api_key=api_key)


# ---------------------------------------------------------------
# Compact catalog — sends FAR fewer tokens to Groq
# ---------------------------------------------------------------
@functools.lru_cache(maxsize=1)
def _compact_catalog():
    """Single-line-per-product compact catalog. Refreshes only on process restart."""
    lines = []
    for p in list_products():
        lines.append(f"{p['name']}|{p['unit']}|{p['unit_price']}")
    return "\n".join(lines)


DIVISIBLE_UNITS = {"kg", "gram", "litre", "ml"}


# ---------------------------------------------------------------
# LOCAL regex parser — no API call, never fails, used as fallback
# ---------------------------------------------------------------
def _local_parse(message: str) -> dict:
    """
    Regex-based backup parser. Handles the most common patterns so the
    app works even when Groq is rate-limited or offline.
    """
    msg = message.lower().strip()
    products = []
    spend_orders = []
    unknown = []

    # Small alias → catalog name mapping
    ALIAS_HINTS = {
        "atta": "atta", "aata": "atta", "flour": "atta",
        "chawal": "rice", "rice": "rice",
        "doodh": "milk", "milk": "milk", "dudh": "milk",
        "anday": "eggs", "anda": "eggs", "egg": "eggs", "eggs": "eggs",
        "cheeni": "sugar", "sugar": "sugar", "shakar": "sugar",
        "namak": "salt", "salt": "salt",
        "tel": "oil", "oil": "oil",
        "patti": "tea", "chai": "tea", "tea": "tea",
        "bread": "bread", "roti": "bread",
        "sabun": "soap", "soap": "soap",
        "pani": "water", "water": "water",
        "chips": "lays", "lays": "lays",
        "biscuit": "biscuit",
        "shampoo": "shampoo",
        "cheese": "cheese", "paneer": "cheese",
        "butter": "butter", "makhan": "butter",
        "yogurt": "yogurt", "dahi": "yogurt",
        "dalda": "dalda", "ghee": "dalda",
        "shakkar": "sugar",
        "biscuits": "biscuit",
    }

    # ---- Spend orders: "100 ka tel", "200 ke eggs", "50 rupees of oil" ----
    spend_pattern = re.compile(
        r"(\d+)\s*(?:rs|rupay|rupaye|pkr|rupees?|ka|ke|ki|of)\s+([a-z]+)",
        re.IGNORECASE
    )
    for m in spend_pattern.finditer(msg):
        amount = float(m.group(1))
        word = m.group(2).lower()
        real = find_product(word) or find_product(ALIAS_HINTS.get(word, ""))
        if real:
            spend_orders.append({
                "product": real["name"],
                "product_id": real["id"],
                "amount": amount,
                "unit": real["unit"],
                "unit_price": float(real["unit_price"]),
                "computed_quantity": round(amount / float(real["unit_price"]), 2),
                "fulfilment": "fraction" if real["unit"].lower() in DIVISIBLE_UNITS else "full_units_with_leftover",
                "full_units": int(amount // float(real["unit_price"])),
                "leftover": round(amount - (int(amount // float(real["unit_price"])) * float(real["unit_price"])), 2),
                "stock_available": float(real["current_stock"]),
                "exceeds_stock": False,
            })

    # ---- Quantity orders: "2kg atta", "1 dozen eggs", "half milk" ----
    # Try "num unit product" first
    qty_pattern = re.compile(
        r"(\d+(?:\.\d+)?|half|aadha|quarter|pao)\s*"
        r"(kg|kilo|kgs|gram|g|litre|liter|l|ml|dozen|piece|pieces|pack|packet|bag|bottle|pcs|pc)?\s+"
        r"([a-z]+)",
        re.IGNORECASE
    )
    FRACTIONS = {"half": 0.5, "aadha": 0.5, "quarter": 0.25, "pao": 0.25}

    for m in qty_pattern.finditer(msg):
        raw_qty = m.group(1).lower()
        qty = FRACTIONS.get(raw_qty, None)
        if qty is None:
            try:
                qty = float(raw_qty)
            except ValueError:
                continue
        word = m.group(3).lower()
        real = find_product(word) or find_product(ALIAS_HINTS.get(word, ""))
        if real:
            # skip if already covered by spend order
            if any(s["product"] == real["name"] for s in spend_orders):
                continue
            products.append({
                "product": real["name"],
                "product_id": real["id"],
                "quantity": qty,
                "unit": real["unit"],
                "unit_price": float(real["unit_price"]),
                "stock_available": float(real["current_stock"]),
                "exceeds_stock": qty > float(real["current_stock"]),
            })

    # ---- Detect unknown product words (bigrams that aren't in catalog) ----
    if not products and not spend_orders:
        # If nothing matched at all, try single-word product lookup
        for word in re.findall(r"[a-z]+", msg):
            real = find_product(word) or find_product(ALIAS_HINTS.get(word, ""))
            if real:
                products.append({
                    "product": real["name"],
                    "product_id": real["id"],
                    "quantity": 1.0,
                    "unit": real["unit"],
                    "unit_price": float(real["unit_price"]),
                    "stock_available": float(real["current_stock"]),
                    "exceeds_stock": False,
                })
                break

    return {
        "intent": "order_intent" if (products or spend_orders) else "other",
        "language": "ur_roman" if any(w in msg for w in ["hai", "ka", "ke", "aur", "chahiye", "do"]) else "en",
        "products": products,
        "spend_orders": spend_orders,
        "unit_mismatch": [],
        "unknown": unknown,
        "_source": "local_regex",   # debug marker
    }


# ---------------------------------------------------------------
# Classifier prompt — compact catalog
# ---------------------------------------------------------------
CLASSIFIER_PROMPT = """Classify the customer message for a Pakistani kiryana shop.

CATALOG (name|unit|price):
{catalog}

Pick ONE intent: greeting | product_query | inventory_query | price_query | order_intent | spend_based_order | confirm | cancel | other

EXTRACT ALL items in one message. Return valid JSON:
{{"intent":"order_intent","language":"en","products":[{{"product":"Atta 5kg","quantity":2,"unit":"bag"}}],"spend_orders":[],"unit_mismatch":[],"unknown":[]}}

RULES:
- Multiple items separated by commas/and/aur → all extracted.
- "100 ka tel" → spend_orders:[{{"product":"Cooking Oil 1L","amount":100}}]
- "10 kg aata" → pick Atta 10kg with quantity 1
- "half milk" → quantity 0.5
- Unknown products → "unknown" array
- Currency always "Rs."

EXAMPLES:
"hi" → {{"intent":"greeting","language":"en","products":[],"spend_orders":[],"unit_mismatch":[],"unknown":[]}}
"2kg atta, 3 eggs, half milk" → {{"intent":"order_intent","language":"ur_roman","products":[{{"product":"Atta 5kg","quantity":1,"unit":"bag"}},{{"product":"Eggs 12 pcs","quantity":3,"unit":"dozen"}},{{"product":"Milk 1L","quantity":0.5,"unit":"piece"}}],"spend_orders":[],"unit_mismatch":[],"unknown":[]}}
"i need 10 kg aata, 1 dozen eggs and 2 litre oil" → {{"intent":"order_intent","language":"en","products":[{{"product":"Atta 10kg","quantity":1,"unit":"bag"}},{{"product":"Eggs 12 pcs","quantity":1,"unit":"dozen"}},{{"product":"Cooking Oil 1L","quantity":2,"unit":"bottle"}}],"spend_orders":[],"unit_mismatch":[],"unknown":[]}}
"100 ka tel" → {{"intent":"spend_based_order","language":"ur_roman","products":[],"spend_orders":[{{"product":"Cooking Oil 1L","amount":100,"unit":"currency"}}],"unit_mismatch":[],"unknown":[]}}
"1 pizza" → {{"intent":"order_intent","language":"en","products":[],"spend_orders":[],"unit_mismatch":[],"unknown":["pizza"]}}
"stock me kia kia hai?" → {{"intent":"inventory_query","language":"ur_roman","products":[],"spend_orders":[],"unit_mismatch":[],"unknown":[]}}
"""


def classify_message(message: str, max_retries: int = 2) -> dict:
    """
    Try Groq classifier with retries. On total failure, use local regex parser.
    Never returns empty silently.
    """
    catalog = _compact_catalog()
    prompt = CLASSIFIER_PROMPT.replace("{catalog}", catalog)

    last_error = None
    for attempt in range(max_retries):
        try:
            client = get_client()
            resp = client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": message},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=600,
            )
            parsed = json.loads(resp.choices[0].message.content)

            # ---- Validate regular products ----
            validated = []
            unknown = list(parsed.get("unknown", []))
            for item in parsed.get("products", []):
                real = find_product(item.get("product", ""))
                if real:
                    qty = float(item.get("quantity", 0))
                    validated.append({
                        "product": real["name"],
                        "product_id": real["id"],
                        "quantity": qty,
                        "unit": real["unit"],
                        "unit_price": float(real["unit_price"]),
                        "stock_available": float(real["current_stock"]),
                        "exceeds_stock": qty > float(real["current_stock"]),
                    })
                else:
                    unknown.append(item.get("product"))

            # ---- Validate spend orders ----
            validated_spend = []
            for so in parsed.get("spend_orders", []):
                real = find_product(so.get("product", ""))
                amount = float(so.get("amount", 0))
                if not real or amount <= 0:
                    if not real:
                        unknown.append(so.get("product"))
                    continue
                up = float(real["unit_price"])
                full = int(amount // up) if up > 0 else 0
                frac = round(amount / up, 2)
                left = round(amount - full * up, 2)
                is_div = real["unit"].lower() in DIVISIBLE_UNITS
                validated_spend.append({
                    "product": real["name"],
                    "product_id": real["id"],
                    "amount": amount,
                    "unit": real["unit"],
                    "unit_price": up,
                    "computed_quantity": frac if is_div else full,
                    "fulfilment": "fraction" if is_div else ("full_units_with_leftover" if full >= 1 else "insufficient"),
                    "full_units": full,
                    "leftover": left,
                    "stock_available": float(real["current_stock"]),
                    "exceeds_stock": (frac if is_div else full) > float(real["current_stock"]),
                })

            result = {
                "intent": parsed.get("intent", "other"),
                "language": parsed.get("language", "en"),
                "products": validated,
                "spend_orders": validated_spend,
                "unit_mismatch": parsed.get("unit_mismatch", []),
                "unknown": unknown,
                "_source": "groq",
            }

            # If classifier returned NOTHING for a real order, try the local parser
            if not validated and not validated_spend and not unknown:
                local = _local_parse(message)
                if local["products"] or local["spend_orders"]:
                    return local

            return result

        except Exception as e:
            last_error = str(e)
            err_lower = last_error.lower()
            is_rate_limit = "rate" in err_lower or "429" in err_lower or "quota" in err_lower
            if is_rate_limit and attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # 1s, 2s backoff
                continue
            break

    # ---- All retries failed — fall back to local regex parser ----
    local = _local_parse(message)
    local["_error"] = last_error
    return local


# ---------------------------------------------------------------
# Responder
# ---------------------------------------------------------------
RESPONDER_PROMPT = """You are DukaanAI — a friendly kiryana shop assistant in Pakistan.

CURRENCY: always "Rs.XXX" (never ₹ or $).
LANGUAGE: reply in the customer's language.

RULES:
- Warm, brief, human. 1–5 sentences.
- Use ONLY facts in data below. Never invent prices/stock/products.
- Never mention AI/LLM.
- No emojis unless the customer used one.

DATA SECTIONS:
- "added_items": products added to draft (confirm briefly)
- "spend_orders": amount-based requests (explain Rs.X = qty units at Rs.Y each)
- "current_draft": running draft
- "product" / "all_items": query context

FACTUAL DATA:
{data}

Plain text only.
"""


def generate_reply(customer_message: str, intent: str, data: dict, language: str) -> str:
    try:
        client = get_client()
        prompt = RESPONDER_PROMPT.replace("{data}", json.dumps(data, indent=2, ensure_ascii=False))
        lang_hint = {
            "en": "Reply in English. Currency: Rs.",
            "ur_roman": "Reply in Roman Urdu. Currency: Rs.",
            "ur": "Reply in Urdu script. Currency: Rs.",
        }.get(language, "Reply in English. Currency: Rs.")

        resp = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"{lang_hint}\nCustomer: {customer_message}\nIntent: {intent}"},
            ],
            temperature=0.4,
            max_tokens=500,
        )
        text = resp.choices[0].message.content.strip()
        return text.replace("₹", "Rs.").replace("$", "Rs.")
    except Exception:
        return _fallback_reply(intent, data, language)


def _fallback_reply(intent, data, language):
    is_ur = language in ("ur_roman", "ur")

    if intent == "greeting":
        return "Assalam-o-Alaikum! Kya chahiye?" if is_ur else "Hi! How can I help you?"

    if intent == "spend_based_order":
        orders = data.get("spend_orders", [])
        if not orders:
            return "Samajh nahi paya — dobara bata dein?" if is_ur else "Couldn't understand — please repeat."
        lines = []
        for o in orders:
            f = o.get("fulfilment")
            if f == "fraction":
                lines.append(
                    f"Rs.{o['amount']} mein {o['computed_quantity']} {o['unit']} "
                    f"{o['product']} milega (Rs.{o['unit_price']}/{o['unit']})."
                    if is_ur else
                    f"Rs.{o['amount']} gets you {o['computed_quantity']} {o['unit']} of {o['product']}."
                )
            elif f == "full_units_with_leftover":
                lines.append(
                    f"Rs.{o['amount']} mein {o['full_units']} {o['unit']} {o['product']} "
                    f"mil sakta hai, Rs.{o['leftover']} bachega."
                    if is_ur else
                    f"Rs.{o['amount']} → {o['full_units']} {o['unit']} of {o['product']}, Rs.{o['leftover']} leftover."
                )
            else:
                lines.append(
                    f"Rs.{o['amount']} mein ek {o['unit']} bhi nahi milta — ek {o['unit']} Rs.{o['unit_price']} hai."
                    if is_ur else
                    f"Rs.{o['amount']} isn't enough for one {o['unit']} (Rs.{o['unit_price']})."
                )
        return " ".join(lines) + (" Confirm karein?" if is_ur else " Shall I add this?")

    if intent == "unit_mismatch":
        m = data.get("mismatch", {})
        return (
            f"Maaf kijiye, {m.get('product')} {m.get('catalog_unit')} mein bikta hai."
            if is_ur else
            f"Sorry, {m.get('product')} is sold by {m.get('catalog_unit')}."
        )

    if intent == "inventory_query":
        items = data.get("all_items", [])
        if not items:
            return "Abhi stock khali hai." if is_ur else "Currently the shop is empty."
        lines = [f"- {it['name']}: Rs.{it['unit_price']}/{it['unit']} ({it['stock']} available)" for it in items]
        header = "Yeh sab items available hain:" if is_ur else "These are all available items:"
        return header + "\n" + "\n".join(lines)

    if intent == "product_query" and data.get("product"):
        p = data["product"]
        return (
            f"{p['name']} available hai — Rs.{p['unit_price']}/{p['unit']}, {p['stock']} bacha hai."
            if is_ur else
            f"{p['name']} is Rs.{p['unit_price']}/{p['unit']}, {p['stock']} in stock."
        )

    if intent == "price_query" and data.get("product"):
        p = data["product"]
        return (
            f"{p['name']} Rs.{p['unit_price']}/{p['unit']} hai."
            if is_ur else
            f"{p['name']} is Rs.{p['unit_price']}/{p['unit']}."
        )

    if intent == "order_intent" and data.get("added_items"):
        names = ", ".join(f"{a['qty']} {a['unit']} {a['name']}" for a in data["added_items"])
        total = data.get("draft_total", 0)
        return (
            f"Theek hai — {names}. Total: Rs.{total}."
            if is_ur else
            f"Added: {names}. Running total: Rs.{total}."
        )

    if intent == "confirm":
        return "Confirm karne ke liye neeche Confirm Order dabaiye." if is_ur else "Click Confirm Order below."

    return "Dobara bata dein?" if is_ur else "Could you say that again?"


def parse_order(message: str) -> dict:
    result = classify_message(message)
    return {
        "items": [p for p in result["products"] if p["quantity"] > 0],
        "unknown": result.get("unknown", []),
    }
