import os
import json
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
# Unit compatibility table — how to convert common user units
# ---------------------------------------------------------------
# Soft conversion: same physical quantity, different label
SOFT_UNIT_MAP = {
    # user_unit → catalog_unit  (multiplier applied to quantity)
    ("litre", "bottle"): 1.0,
    ("liter", "bottle"): 1.0,
    ("l", "bottle"): 1.0,
    ("kg", "bag"): 1.0,
    ("kilo", "bag"): 1.0,
    ("gram", "pack"): 1.0,
    ("g", "pack"): 1.0,
    ("piece", "piece"): 1.0,
    ("pieces", "piece"): 1.0,
    ("dozen", "dozen"): 1.0,
    ("pack", "pack"): 1.0,
    ("packet", "pack"): 1.0,
    ("bottle", "bottle"): 1.0,
    ("bag", "bag"): 1.0,
    ("ml", "bottle"): 0.001,   # 1000ml = 1 bottle
}

DIVISIBLE_UNITS = {"kg", "gram", "litre", "ml"}


def get_product_catalog():
    products = list_products()
    return [
        {
            "name": p["name"],
            "aliases": p["aliases"],
            "unit": p["unit"],
            "price_per_unit": p["unit_price"],
            "stock_available": p["current_stock"],
        }
        for p in products
    ]


CLASSIFIER_PROMPT = """You are the intent classifier for DukaanAI, an AI shop assistant at a Pakistani kiryana store.

CURRENCY: Always "Rs." — never ₹, $.

Classify into EXACTLY ONE intent:
- "greeting"           → hi, hello, salam, assalam, hey, aoaa
- "product_query"      → asks about availability/price/stock of a SPECIFIC product
- "inventory_query"    → asks what products exist in the shop
- "price_query"        → asks price ONLY of a specific product
- "order_intent"       → orders with quantities (kg, dozen, pack, litre, bottle, etc.)
- "spend_based_order"  → orders by amount (100 ka tel, 200 rs eggs)
- "confirm"            → yes, haan, ok, confirm, theek hai
- "cancel"             → no, nahi, cancel, chhoro
- "other"              → anything else

THE MOST IMPORTANT RULE:
When the customer lists MULTIPLE items separated by commas, "and", "aur", "yaan",
or simply spaces, EXTRACT EVERY SINGLE ONE into the "products" array.
Do NOT skip any. Do NOT summarize. Do NOT leave products empty for a
compound order.

CRITICAL RULES:

1. MULTI-ITEM EXTRACTION — extract ALL items, always:
   "2kg atta, 3 eggs, half milk"        → 3 products
   "10 kg aata, 1 dozen eggs, 2 litre oil" → 3 products
   "1kg cheeni, 2 bread, 3 doodh"       → 3 products

2. UNIT SELECTION — pick the closest-matching SKU from the catalog:
   "2 litre oil"      → Cooking Oil 1L  (unit: bottle, quantity: 2)
   "10 kg aata"       → Atta 10kg       (unit: bag, quantity: 1)   ← pick 10kg SKU directly
   "2 kg atta"        → Atta 5kg        (unit: bag, quantity: 1)   ← if 2kg has no SKU
   "half milk"        → Milk 1L         (unit: piece, quantity: 0.5)
   "1 dozen eggs"     → Eggs 12 pcs     (unit: dozen, quantity: 1)

3. If a numeric amount matches a specific SKU name (e.g. "10 kg atta" → "Atta 10kg"),
   USE THAT SKU with quantity=1. Do NOT pick Atta 5kg and set quantity=2.

4. FRACTIONS: "half" → 0.5, "quarter" → 0.25, "aadha" → 0.5, "pao" → 0.25.

5. SPEND-BASED: "100 ka tel" → spend_orders, product = Cooking Oil 1L, amount = 100.

6. UNKNOWN: any product NOT in catalog → "unknown". Never invent.

7. IGNORE filler: please, bhai, yaar, kindly, I want, mujhe chahiye, dedo, chahiye.

CATALOG:
{catalog}

OUTPUT (strict JSON):
{{
  "intent": "order_intent",
  "language": "ur_roman",
  "products": [{{"product": "Atta 10kg", "quantity": 1, "unit": "bag"}}],
  "spend_orders": [],
  "unit_mismatch": [],
  "unknown": []
}}

EXAMPLES — study these carefully:

"hi" → {{"intent":"greeting","language":"en","products":[],"spend_orders":[],"unit_mismatch":[],"unknown":[]}}

"doodh available hai?" → {{"intent":"product_query","language":"ur_roman","products":[{{"product":"Milk 1L","quantity":0,"unit":"piece"}}],"spend_orders":[],"unit_mismatch":[],"unknown":[]}}

"2kg atta, 3 eggs, half milk" → {{"intent":"order_intent","language":"ur_roman","products":[{{"product":"Atta 5kg","quantity":1,"unit":"bag"}},{{"product":"Eggs 12 pcs","quantity":3,"unit":"dozen"}},{{"product":"Milk 1L","quantity":0.5,"unit":"piece"}}],"spend_orders":[],"unit_mismatch":[],"unknown":[]}}

"i need 10 kg aata, 1 dozen eggs and 2 litre oil" → {{"intent":"order_intent","language":"en","products":[{{"product":"Atta 10kg","quantity":1,"unit":"bag"}},{{"product":"Eggs 12 pcs","quantity":1,"unit":"dozen"}},{{"product":"Cooking Oil 1L","quantity":2,"unit":"bottle"}}],"spend_orders":[],"unit_mismatch":[],"unknown":[]}}

"2 kg atta aur 1 bottle oil" → {{"intent":"order_intent","language":"ur_roman","products":[{{"product":"Atta 5kg","quantity":1,"unit":"bag"}},{{"product":"Cooking Oil 1L","quantity":1,"unit":"bottle"}}],"spend_orders":[],"unit_mismatch":[],"unknown":[]}}

"100 pkr ka cooking oil" → {{"intent":"spend_based_order","language":"ur_roman","products":[],"spend_orders":[{{"product":"Cooking Oil 1L","amount":100,"unit":"currency"}}],"unit_mismatch":[],"unknown":[]}}

"2 kg tea" → {{"intent":"order_intent","language":"en","products":[],"spend_orders":[],"unit_mismatch":[{{"product":"Tapal Tea 950g","customer_said_unit":"kg","catalog_unit":"pack"}}],"unknown":[]}}

"1 pizza" → {{"intent":"order_intent","language":"en","products":[],"spend_orders":[],"unit_mismatch":[],"unknown":["pizza"]}}

"stock me kia kia hai?" → {{"intent":"inventory_query","language":"ur_roman","products":[],"spend_orders":[],"unit_mismatch":[],"unknown":[]}}
"""


def classify_message(message: str) -> dict:
    client = get_client()
    catalog = get_product_catalog()
    prompt = CLASSIFIER_PROMPT.replace("{catalog}", json.dumps(catalog, indent=2))

    try:
        resp = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": message},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=900,
        )
        parsed = json.loads(resp.choices[0].message.content)

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

        # ---- spend orders ----
        validated_spend = []
        for so in parsed.get("spend_orders", []):
            real = find_product(so.get("product", ""))
            amount = float(so.get("amount", 0))
            if not real or amount <= 0:
                if not real:
                    unknown.append(so.get("product"))
                continue

            unit_price = float(real["unit_price"])
            unit = real["unit"]
            full_units = int(amount // unit_price) if unit_price > 0 else 0
            leftover = round(amount - full_units * unit_price, 2)
            fractional_qty = round(amount / unit_price, 2)
            is_divisible = unit.lower() in DIVISIBLE_UNITS

            if is_divisible:
                validated_spend.append({
                    "product": real["name"], "product_id": real["id"],
                    "amount": amount, "unit": unit, "unit_price": unit_price,
                    "computed_quantity": fractional_qty,
                    "fulfilment": "fraction",
                    "full_units": full_units, "leftover": leftover,
                    "stock_available": float(real["current_stock"]),
                    "exceeds_stock": fractional_qty > float(real["current_stock"]),
                })
            else:
                if full_units >= 1:
                    validated_spend.append({
                        "product": real["name"], "product_id": real["id"],
                        "amount": amount, "unit": unit, "unit_price": unit_price,
                        "computed_quantity": full_units,
                        "fulfilment": "full_units_with_leftover",
                        "full_units": full_units, "leftover": leftover,
                        "stock_available": float(real["current_stock"]),
                        "exceeds_stock": full_units > float(real["current_stock"]),
                    })
                else:
                    validated_spend.append({
                        "product": real["name"], "product_id": real["id"],
                        "amount": amount, "unit": unit, "unit_price": unit_price,
                        "computed_quantity": 0,
                        "fulfilment": "insufficient",
                        "full_units": 0, "leftover": amount,
                        "stock_available": float(real["current_stock"]),
                        "exceeds_stock": False,
                    })

        return {
            "intent": parsed.get("intent", "other"),
            "language": parsed.get("language", "en"),
            "products": validated,
            "spend_orders": validated_spend,
            "unit_mismatch": parsed.get("unit_mismatch", []),
            "unknown": unknown,
        }

    except Exception as e:
        return {
            "intent": "other", "language": "en",
            "products": [], "spend_orders": [],
            "unit_mismatch": [], "unknown": [],
            "error": str(e),
        }


RESPONDER_PROMPT = """You are DukaanAI — a friendly shopkeeper's assistant at a small neighbourhood store in Pakistan.

CURRENCY: Always "Rs.XXX" — never ₹, $.

LANGUAGE: Reply in the SAME language as the customer.

STYLE:
- Warm, brief, human. 1–6 short sentences.
- Use ONLY facts in the data. NEVER invent prices, stock, or quantities.
- NEVER mention AI / LLM.
- No emojis unless the customer used one.

You may receive these data sections:
  A. "added_items"     — regular products that were just added to the draft
  B. "spend_orders"    — spend-based requests (explain + ask)
  C. "current_draft"   — running draft
  D. "product" / "all_items" — query context

RULES:
1. If "added_items" present → briefly list what was added and mention running total.
2. If "spend_orders" present → for each:
   - fulfilment "fraction": "Rs.X mein [qty] [unit] [product] milega (Rs.Y/[unit])."
   - fulfilment "full_units_with_leftover": "Rs.X mein [N] [unit] mil sakta hai, Rs.L bachega."
   - fulfilment "insufficient": "Rs.X mein ek [unit] bhi nahi milta — ek [unit] Rs.Y hai."
3. If BOTH A and B present → confirm A briefly, then explain B, then ask "Confirm karein?"
4. If "current_draft" present → mention the running total.

FACTUAL DATA (authoritative — quote exactly, use Rs.):
{data}

Output plain text only.
"""


def generate_reply(customer_message: str, intent: str, data: dict, language: str) -> str:
    client = get_client()
    prompt = RESPONDER_PROMPT.replace("{data}", json.dumps(data, indent=2, ensure_ascii=False))
    lang_hint = {
        "en": "Reply in English. Use Rs. as currency.",
        "ur_roman": "Reply in Roman Urdu. Use Rs. as currency.",
        "ur": "Reply in Urdu script. Use Rs. as currency.",
    }.get(language, "Reply in English. Use Rs. as currency.")

    try:
        resp = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"{lang_hint}\n\nCustomer said: {customer_message}\nDetected intent: {intent}"},
            ],
            temperature=0.4,
            max_tokens=700,
        )
        text = resp.choices[0].message.content.strip()
        text = text.replace("₹", "Rs.").replace("$", "Rs.")
        return text
    except Exception:
        return _fallback_reply(intent, data, language)


def _fallback_reply(intent, data, language):
    is_ur = language in ("ur_roman", "ur")

    if intent == "greeting":
        return "Assalam-o-Alaikum! Kya chahiye?" if is_ur else "Hi! How can I help you?"

    if intent == "spend_based_order":
        orders = data.get("spend_orders", [])
        if not orders:
            return "Samajh nahi paya — dobara bata dein?" if is_ur else "Could not understand — please repeat."
        lines = []
        for o in orders:
            f = o.get("fulfilment")
            if f == "fraction":
                lines.append(
                    f"Rs.{o['amount']} mein {o['computed_quantity']} {o['unit']} "
                    f"{o['product']} milega (Rs.{o['unit_price']}/{o['unit']})."
                    if is_ur else
                    f"Rs.{o['amount']} gets you {o['computed_quantity']} {o['unit']} "
                    f"of {o['product']} (Rs.{o['unit_price']}/{o['unit']})."
                )
            elif f == "full_units_with_leftover":
                lines.append(
                    f"Rs.{o['amount']} mein {o['full_units']} {o['unit']} {o['product']} "
                    f"mil sakta hai, Rs.{o['leftover']} bachega."
                    if is_ur else
                    f"Rs.{o['amount']} gets you {o['full_units']} {o['unit']} of "
                    f"{o['product']}, leaving Rs.{o['leftover']}."
                )
            elif f == "insufficient":
                lines.append(
                    f"Rs.{o['amount']} mein ek {o['unit']} bhi nahi milta — ek {o['unit']} Rs.{o['unit_price']} hai."
                    if is_ur else
                    f"Rs.{o['amount']} isn't enough for one {o['unit']} — one {o['unit']} costs Rs.{o['unit_price']}."
                )
        tail = "Confirm karein?" if is_ur else "Shall I add this?"
        return " ".join(lines) + " " + tail

    if intent == "unit_mismatch":
        m = data.get("mismatch", {})
        if is_ur:
            return f"Maaf kijiye, {m.get('product')} {m.get('catalog_unit')} mein bikta hai — quantity batayein."
        return f"Sorry, {m.get('product')} is sold by {m.get('catalog_unit')}. Please give the quantity."

    if intent == "inventory_query":
        items = data.get("all_items", [])
        if not items:
            return "Abhi stock khali hai." if is_ur else "Currently the shop is empty."
        lines = [
            f"- {it['name']}: Rs.{it['unit_price']}/{it['unit']} ({it['stock']} available)"
            for it in items
        ]
        header = "Yeh sab items available hain:" if is_ur else "These are all available items:"
        return header + "\n" + "\n".join(lines)

    if intent == "product_query" and data.get("product"):
        p = data["product"]
        return (
            f"Haan, {p['name']} available hai — Rs.{p['unit_price']} per {p['unit']}, "
            f"{p['stock']} {p['unit']} bacha hai."
            if is_ur else
            f"Yes, {p['name']} is available — Rs.{p['unit_price']} per {p['unit']}, "
            f"{p['stock']} {p['unit']} in stock."
        )

    if intent == "price_query" and data.get("product"):
        p = data["product"]
        return (
            f"{p['name']} ka rate Rs.{p['unit_price']} per {p['unit']} hai."
            if is_ur else
            f"{p['name']} is Rs.{p['unit_price']} per {p['unit']}."
        )

    if intent == "order_intent" and data.get("added_items"):
        names = ", ".join(
            f"{a['qty']} {a['unit']} {a['name']}" for a in data["added_items"]
        )
        total = data.get("draft_total", 0)
        return (
            f"Theek hai, add kar diya: {names}. Total ab Rs.{total} hai."
            if is_ur else
            f"Added: {names}. Running total: Rs.{total}."
        )

    if intent == "confirm":
        return "Confirm karne ke liye neeche Confirm Order button dabaiye." if is_ur else \
               "Click Confirm Order below."

    return "Dobara bata dein?" if is_ur else "Could you say that again?"


def parse_order(message: str) -> dict:
    result = classify_message(message)
    return {
        "items": [p for p in result["products"] if p["quantity"] > 0],
        "unknown": result.get("unknown", []),
    }
