import os
import json
import functools
import math
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
# Divisible vs indivisible units
# ---------------------------------------------------------------
DIVISIBLE_UNITS = {"kg", "gram", "litre", "ml"}
INDIVISIBLE_UNITS = {"piece", "dozen", "bag", "pack", "bottle", "packet"}


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


# ---------------------------------------------------------------
# Classifier prompt — v2
# ---------------------------------------------------------------
CLASSIFIER_PROMPT = """You are the intent classifier for DukaanAI, an AI shop assistant.

Currency is ALWAYS "Rs." — never ₹, $, or any other symbol.

Classify into EXACTLY ONE intent:
- "greeting"           → hi, hello, salam, assalam, hey, aoaa
- "product_query"      → asks about availability/price/stock of a SPECIFIC product
- "inventory_query"    → asks what products exist in the shop
- "price_query"        → asks price ONLY of a specific product
- "order_intent"       → orders with quantities (kg, dozen, pack, etc.)
- "spend_based_order"  → orders by amount (100 ka tel, 200 rs eggs)
- "confirm"            → yes, haan, ok, confirm, theek hai
- "cancel"             → no, nahi, cancel, chhoro
- "other"              → anything else

CRITICAL RULES:

1. EXTRACT ALL items from a message. "2kg atta, 3 eggs, half milk" → 3 items.

2. UNIT MATCHING: only use the catalog's unit. If the customer uses a
   different unit → put in "unit_mismatch". Never auto-convert.

3. FRACTIONS: "half milk" → 0.5, "aadha kg chawal" → 0.5, "1.5 kg sugar" → 1.5.

4. SPEND-BASED: "100 ka tel" → spend_orders with product + amount (100).
   The customer's amount is in rupees.

5. UNKNOWN PRODUCTS: any product NOT in the catalog → "unknown". Never invent.

6. IGNORE filler: please, bhai, yaar, kindly, I want, mujhe chahiye.

CATALOG:
{catalog}

OUTPUT (strict JSON):
{{
  "intent": "order_intent",
  "language": "ur_roman",
  "products": [{{"product": "Atta 5kg", "quantity": 2, "unit": "bag"}}],
  "spend_orders": [],
  "unit_mismatch": [],
  "unknown": []
}}

EXAMPLES:
"hi"                              → {{"intent":"greeting","language":"en","products":[],"spend_orders":[],"unit_mismatch":[],"unknown":[]}}
"doodh available hai?"            → {{"intent":"product_query","language":"ur_roman","products":[{{"product":"Milk 1L","quantity":0,"unit":"piece"}}],"spend_orders":[],"unit_mismatch":[],"unknown":[]}}
"2kg atta, 3 eggs, half milk"     → {{"intent":"order_intent","language":"ur_roman","products":[{{"product":"Atta 5kg","quantity":2,"unit":"bag"}},{{"product":"Eggs 12 pcs","quantity":3,"unit":"dozen"}},{{"product":"Milk 1L","quantity":0.5,"unit":"piece"}}],"spend_orders":[],"unit_mismatch":[],"unknown":[]}}
"100 pkr ka cooking oil"          → {{"intent":"spend_based_order","language":"ur_roman","products":[],"spend_orders":[{{"product":"Cooking Oil 1L","amount":100,"unit":"currency"}}],"unit_mismatch":[],"unknown":[]}}
"200 ke eggs dedo"                → {{"intent":"spend_based_order","language":"ur_roman","products":[],"spend_orders":[{{"product":"Eggs 12 pcs","amount":200,"unit":"currency"}}],"unit_mismatch":[],"unknown":[]}}
"50 ka aata aur 100 ka chawal"    → {{"intent":"spend_based_order","language":"ur_roman","products":[],"spend_orders":[{{"product":"Atta 5kg","amount":50,"unit":"currency"}},{{"product":"Basmati Rice 2kg","amount":100,"unit":"currency"}}],"unit_mismatch":[],"unknown":[]}}
"2 kg tea"                        → {{"intent":"order_intent","language":"en","products":[],"spend_orders":[],"unit_mismatch":[{{"product":"Tapal Tea 950g","customer_said_unit":"kg","catalog_unit":"pack"}}],"unknown":[]}}
"1 pizza"                         → {{"intent":"order_intent","language":"en","products":[],"spend_orders":[],"unit_mismatch":[],"unknown":["pizza"]}}
"stock me kia kia hai?"           → {{"intent":"inventory_query","language":"ur_roman","products":[],"spend_orders":[],"unit_mismatch":[],"unknown":[]}}
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
            max_tokens=800,
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

        # ---- Validate spend orders with indivisible-unit logic ----
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

            # ---- Decide how to fulfil ----
            if is_divisible:
                # fraction is fine — just offer fractional_qty
                validated_spend.append({
                    "product": real["name"],
                    "product_id": real["id"],
                    "amount": amount,
                    "unit": unit,
                    "unit_price": unit_price,
                    "computed_quantity": fractional_qty,
                    "fulfilment": "fraction",
                    "full_units": full_units,
                    "leftover": leftover,
                    "stock_available": float(real["current_stock"]),
                    "exceeds_stock": fractional_qty > float(real["current_stock"]),
                })
            else:
                # indivisible — need full units
                if full_units >= 1:
                    validated_spend.append({
                        "product": real["name"],
                        "product_id": real["id"],
                        "amount": amount,
                        "unit": unit,
                        "unit_price": unit_price,
                        "computed_quantity": full_units,
                        "fulfilment": "full_units_with_leftover",
                        "full_units": full_units,
                        "leftover": leftover,
                        "stock_available": float(real["current_stock"]),
                        "exceeds_stock": full_units > float(real["current_stock"]),
                    })
                else:
                    # amount < one unit price
                    validated_spend.append({
                        "product": real["name"],
                        "product_id": real["id"],
                        "amount": amount,
                        "unit": unit,
                        "unit_price": unit_price,
                        "computed_quantity": 0,
                        "fulfilment": "insufficient",
                        "full_units": 0,
                        "leftover": amount,
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
            "intent": "other",
            "language": "en",
            "products": [],
            "spend_orders": [],
            "unit_mismatch": [],
            "unknown": [],
            "error": str(e),
        }


# ---------------------------------------------------------------
# Responder prompt — v2
# ---------------------------------------------------------------
RESPONDER_PROMPT = """You are DukaanAI — a friendly shopkeeper's assistant at a small neighbourhood store in Pakistan.

CURRENCY: Always write prices as "Rs.XXX" — never ₹, $, or any other symbol.

LANGUAGE RULES:
1. Reply in the SAME language as the customer (English → English, Roman Urdu → Roman Urdu, Urdu → Urdu).

STYLE RULES:
2. Warm, brief, human. 1–5 short sentences.
3. Use ONLY the facts in the data below. NEVER invent prices, stock, product names, or quantities.
4. NEVER say "I don't have information" if data is provided.
5. NEVER mention AI / LLM.
6. No emojis unless the customer used one.

SPEND-BASED ORDER RULES (CRITICAL):
7. When the customer's spend order has "fulfilment": "fraction":
   - Say: "Rs.X mein aap ko [quantity] [unit] [product] milega (Rs.Y/[unit])."
   - Ask to confirm.

8. When fulfilment is "full_units_with_leftover":
   - Say: "Rs.X mein [N] [unit] [product] mil sakta hai. Yeh Rs.Z hoga, aur Rs.L bacha rahega."
   - Ask: "Kya aap yeh [N] [unit] lena chahenge?"

9. When fulfilment is "insufficient":
   - Say: "Rs.X mein ek [unit] bhi nahi milta — ek [unit] ki keemat Rs.Y hai. Kitna lena chahenge?"

10. If "exceeds_stock" is true: say only stock number available and ask if they want that much.

FACTUAL DATA (authoritative — quote exactly, use Rs.):
{data}

Output plain text only. No JSON.
"""


def generate_reply(customer_message: str, intent: str, data: dict, language: str) -> str:
    client = get_client()
    prompt = RESPONDER_PROMPT.replace("{data}", json.dumps(data, indent=2, ensure_ascii=False))
    lang_hint = {
        "en": "Reply in English. Use Rs. as the currency symbol.",
        "ur_roman": "Reply in Roman Urdu. Use Rs. as the currency symbol.",
        "ur": "Reply in Urdu script. Use Rs. as the currency symbol.",
    }.get(language, "Reply in English. Use Rs. as the currency symbol.")

    try:
        resp = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": f"{lang_hint}\n\nCustomer said: {customer_message}\nDetected intent: {intent}",
                },
            ],
            temperature=0.4,
            max_tokens=600,
        )
        text = resp.choices[0].message.content.strip()
        # Safety net: replace ₹ and $ with Rs. in case the LLM slipped
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
                if is_ur:
                    lines.append(
                        f"Rs.{o['amount']} mein {o['computed_quantity']} {o['unit']} "
                        f"{o['product']} milega (Rs.{o['unit_price']}/{o['unit']})."
                    )
                else:
                    lines.append(
                        f"Rs.{o['amount']} gets you {o['computed_quantity']} {o['unit']} "
                        f"of {o['product']} (Rs.{o['unit_price']}/{o['unit']})."
                    )
            elif f == "full_units_with_leftover":
                if is_ur:
                    lines.append(
                        f"Rs.{o['amount']} mein {o['full_units']} {o['unit']} {o['product']} "
                        f"mil sakta hai (Rs.{o['unit_price']}/{o['unit']}). Rs.{o['leftover']} bacha rahega."
                    )
                else:
                    lines.append(
                        f"Rs.{o['amount']} gets you {o['full_units']} {o['unit']} of "
                        f"{o['product']} (Rs.{o['unit_price']}/{o['unit']}), "
                        f"leaving Rs.{o['leftover']}."
                    )
            elif f == "insufficient":
                if is_ur:
                    lines.append(
                        f"Rs.{o['amount']} mein ek {o['unit']} bhi nahi milta — "
                        f"ek {o['unit']} ki keemat Rs.{o['unit_price']} hai."
                    )
                else:
                    lines.append(
                        f"Rs.{o['amount']} isn't enough for one {o['unit']} — "
                        f"one {o['unit']} costs Rs.{o['unit_price']}."
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
        first = data["added_items"][0]
        total = data.get("draft_total", 0)
        return (
            f"Theek hai, {first['qty']} {first['unit']} {first['name']} add kar diya. "
            f"Total ab Rs.{total} hai."
            if is_ur else
            f"Added {first['qty']} {first['unit']} {first['name']}. Total now Rs.{total}."
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
