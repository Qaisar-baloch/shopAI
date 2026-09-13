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
# Classifier prompt — now handles spend-based, fractions, compounds
# ---------------------------------------------------------------
CLASSIFIER_PROMPT = """You are the intent classifier for DukaanAI, an AI shop assistant.

Classify the customer's message into EXACTLY ONE of these intents:
- "greeting"           → hi, hello, salam, assalam, hey, aoaa
- "product_query"      → asks about availability/price/stock of a SPECIFIC product
- "inventory_query"    → asks what products exist in the shop, wants a LIST
- "price_query"        → asks price ONLY of a specific product
- "order_intent"       → wants to order one or more products WITH quantities
- "spend_based_order"  → orders by amount, e.g. "100 ka tel", "200 rs of eggs", "50 rupees chicken"
- "confirm"            → yes, haan, ok, confirm, theek hai
- "cancel"             → no, nahi, cancel, chhoro
- "other"              → anything else

CRITICAL EXTRACTION RULES:

1. A single message may contain MULTIPLE items. Extract ALL of them.
   Example: "2kg atta, 3 eggs, and milk" → 3 items.

2. UNIT MATCHING:
   - Each product is sold ONLY in its catalog "unit".
   - If the customer's unit is DIFFERENT from catalog unit → add to "unit_mismatch".
   - Never auto-convert units (kg ≠ gram, litre ≠ ml).

3. FRACTIONS & QUALITATIVE QUANTITIES:
   - "half milk" → quantity 0.5, product Milk
   - "quarter kg atta" → quantity 0.25, product Atta
   - "aadha kilo chawal" → quantity 0.5, product Rice
   - "one and a half kg sugar" → quantity 1.5

4. SPEND-BASED ORDERS:
   - "100 ka tel" → intent spend_based_order, product Cooking Oil, amount 100
   - "200 rs of eggs" → intent spend_based_order, product Eggs, amount 200
   - "50 rupees of lays" → intent spend_based_order, product Lays, amount 50
   - Format: {{"product": "X", "amount": N, "unit": "currency"}}

5. IGNORE filler words: "please", "bhai", "yaar", "kindly", "I want", "mujhe chahiye".

6. If NO product matches the catalog, return empty products[] and list them in "unknown".

7. If the customer asks about price or quantity in a way that doesn't clearly
   map to any product, use intent "product_query" with empty products — the
   responder will show the full inventory.

CATALOG:
{catalog}

OUTPUT (strict JSON, no markdown):
{{
  "intent": "order_intent",
  "language": "ur_roman",
  "products": [
    {{"product": "Atta", "quantity": 2, "unit": "bag"}},
    {{"product": "Eggs 12 pcs", "quantity": 3, "unit": "dozen"}}
  ],
  "spend_orders": [],
  "unit_mismatch": [],
  "unknown": []
}}

EXAMPLES:

"hi"                                    → {{"intent":"greeting","language":"en","products":[],"spend_orders":[],"unit_mismatch":[],"unknown":[]}}

"doodh available hai?"                  → {{"intent":"product_query","language":"ur_roman","products":[{{"product":"Milk 1L","quantity":0,"unit":"piece"}}],"spend_orders":[],"unit_mismatch":[],"unknown":[]}}

"2kg atta, 3 eggs, half milk"           → {{"intent":"order_intent","language":"ur_roman","products":[{{"product":"Atta 5kg","quantity":2,"unit":"bag"}},{{"product":"Eggs 12 pcs","quantity":3,"unit":"dozen"}},{{"product":"Milk 1L","quantity":0.5,"unit":"piece"}}],"spend_orders":[],"unit_mismatch":[],"unknown":[]}}

"100 pkr ka cooking oil"                → {{"intent":"spend_based_order","language":"ur_roman","products":[],"spend_orders":[{{"product":"Cooking Oil 1L","amount":100,"unit":"currency"}}],"unit_mismatch":[],"unknown":[]}}

"200 ke eggs dedo"                      → {{"intent":"spend_based_order","language":"ur_roman","products":[],"spend_orders":[{{"product":"Eggs 12 pcs","amount":200,"unit":"currency"}}],"unit_mismatch":[],"unknown":[]}}

"50 ka tel aur 100 ka aata"             → {{"intent":"spend_based_order","language":"ur_roman","products":[],"spend_orders":[{{"product":"Cooking Oil 1L","amount":50,"unit":"currency"}},{{"product":"Atta 5kg","amount":100,"unit":"currency"}}],"unit_mismatch":[],"unknown":[]}}

"2 kg tea"                              → {{"intent":"order_intent","language":"en","products":[],"spend_orders":[],"unit_mismatch":[{{"product":"Tapal Tea 950g","customer_said_unit":"kg","catalog_unit":"pack"}}],"unknown":[]}}

"1 pizza"                               → {{"intent":"order_intent","language":"en","products":[],"spend_orders":[],"unit_mismatch":[],"unknown":["pizza"]}}

"stock me kia kia hai?"                 → {{"intent":"inventory_query","language":"ur_roman","products":[],"spend_orders":[],"unit_mismatch":[],"unknown":[]}}
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
            if real and amount > 0:
                unit_price = float(real["unit_price"])
                computed_qty = round(amount / unit_price, 2)
                validated_spend.append({
                    "product": real["name"],
                    "product_id": real["id"],
                    "amount": amount,
                    "unit": real["unit"],
                    "unit_price": unit_price,
                    "computed_quantity": computed_qty,
                    "stock_available": float(real["current_stock"]),
                    "exceeds_stock": computed_qty > float(real["current_stock"]),
                })
            elif not real:
                unknown.append(so.get("product"))

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
# Responder prompt
# ---------------------------------------------------------------
RESPONDER_PROMPT = """You are DukaanAI — a friendly shopkeeper's assistant at a small neighbourhood store.

LANGUAGE RULES:
1. Reply in the SAME language as the customer.

STYLE RULES:
2. Be warm, brief, human. 1–5 short sentences.
3. Use ONLY the facts in the data below. NEVER invent prices, stock, product names, or quantities.
4. NEVER say "I don't have information" if data is provided.
5. NEVER mention AI / LLM.
6. No emojis unless the customer used one.
7. When you confirm a spend-based order, ALWAYS state:
   - the unit price
   - the computed quantity for the amount
   - "confirm karein?" or "shall I add this?"
8. When the customer asked for something outside the catalog, list a few available
   alternatives from "all_items" if provided.

FACTUAL DATA (authoritative — quote exactly):
{data}

Output plain text only. No JSON, no markdown fences.
"""


def generate_reply(customer_message: str, intent: str, data: dict, language: str) -> str:
    client = get_client()
    prompt = RESPONDER_PROMPT.replace("{data}", json.dumps(data, indent=2, ensure_ascii=False))
    lang_hint = {
        "en": "Reply in English.",
        "ur_roman": "Reply in Roman Urdu (English letters, Urdu words).",
        "ur": "Reply in Urdu script.",
    }.get(language, "Reply in English.")

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
            temperature=0.5,
            max_tokens=600,
        )
        return resp.choices[0].message.content.strip()
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
            if is_ur:
                lines.append(
                    f"{o['amount']} rupay mein {o['computed_quantity']} {o['unit']} "
                    f"{o['product']} milega (Rs.{o['unit_price']}/{o['unit']})."
                )
            else:
                lines.append(
                    f"Rs.{o['amount']} gets you {o['computed_quantity']} {o['unit']} of "
                    f"{o['product']} (Rs.{o['unit_price']}/{o['unit']})."
                )
        tail = "Confirm karein?" if is_ur else "Shall I add these?"
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
