import os
import json
import functools
from groq import Groq
from db import find_product, list_products, get_product_by_id


# ---------------------------------------------------------------
# Groq client (cached)
# ---------------------------------------------------------------
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


# ---- CHANGED: include unit in the catalog so the LLM knows how each product is sold ----
def get_product_catalog():
    products = list_products()
    return [
        {
            "name": p["name"],
            "aliases": p["aliases"],
            "unit": p["unit"],           # kg / gram / litre / dozen / piece
            "price_per_unit": p["unit_price"],
            "stock_available": p["current_stock"],
        }
        for p in products
    ]


# ---- CHANGED: stricter classifier prompt with unit rules ----
CLASSIFIER_PROMPT = """You are the intent classifier for DukaanAI, an AI shop assistant.

Classify the customer's message into EXACTLY ONE of these intents:
- "greeting"         → hi, hello, salam, assalam, hey, aoaa
- "product_query"    → asks about availability/price/stock of a SPECIFIC product
- "inventory_query"  → asks what products exist in the shop, wants a LIST
- "price_query"      → asks price ONLY of a specific product
- "order_intent"     → wants to order one or more products WITH quantities
- "confirm"          → yes, haan, ok, confirm, theek hai
- "cancel"           → no, nahi, cancel, chhoro
- "other"            → anything else

CRITICAL UNIT RULES:
1. Each product in the CATALOG is sold ONLY in the unit listed ("unit" field).
2. If the customer uses a DIFFERENT unit than the product's catalog unit, DO NOT auto-convert.
   Instead, mark the item in "unit_mismatch" and explain.
3. Examples of mismatch:
   - Catalog says "gram", customer says "kg" → MISMATCH (do not convert)
   - Catalog says "kg", customer says "gram" → MISMATCH
   - Catalog says "litre", customer says "ml" → MISMATCH
   - Catalog says "piece", customer says "dozen" → MISMATCH
4. If the customer uses the SAME unit as catalog, extract normally.
5. If no unit specified by customer, assume the catalog's unit.

Also extract:
- "products": list of {product, quantity, unit} from catalog (for product_query, price_query, order_intent)
- "unit_mismatch": list of {product, customer_said_unit, catalog_unit} for cross-unit requests
- "language": "en" | "ur_roman" | "ur"

CATALOG:
{catalog}

OUTPUT (strict JSON, no markdown):
{{
  "intent": "order_intent",
  "language": "ur_roman",
  "products": [{{"product":"Milk","quantity":5,"unit":"litre"}}],
  "unit_mismatch": []
}}

EXAMPLES:
"hi"                                 → {{"intent":"greeting","language":"en","products":[],"unit_mismatch":[]}}
"milk available hai?"                → {{"intent":"product_query","language":"ur_roman","products":[{{"product":"Milk","quantity":0,"unit":"litre"}}],"unit_mismatch":[]}}
"2kg atta"                           → {{"intent":"order_intent","language":"ur_roman","products":[{{"product":"Atta","quantity":2,"unit":"kg"}}],"unit_mismatch":[]}}
"I need two kg tea"                  → {{"intent":"order_intent","language":"en","products":[],"unit_mismatch":[{{"product":"Tea","customer_said_unit":"kg","catalog_unit":"gram"}}]}}
"5 litre milk"                       → {{"intent":"order_intent","language":"en","products":[{{"product":"Milk","quantity":5,"unit":"litre"}}],"unit_mismatch":[]}}
"500 gram tea"                       → {{"intent":"order_intent","language":"en","products":[{{"product":"Tea","quantity":500,"unit":"gram"}}],"unit_mismatch":[]}}
"1 dozen eggs"                       → {{"intent":"order_intent","language":"en","products":[{{"product":"Eggs","quantity":1,"unit":"dozen"}}],"unit_mismatch":[]}}
"stock me kia kia hai?"              → {{"intent":"inventory_query","language":"ur_roman","products":[],"unit_mismatch":[]}}
"""


def classify_message(message: str) -> dict:
    """Returns {intent, language, products, unit_mismatch, unknown}."""
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
            max_tokens=500,
        )
        parsed = json.loads(resp.choices[0].message.content)

        validated = []
        unknown = []
        for item in parsed.get("products", []):
            real = find_product(item.get("product", ""))
            if real:
                qty = float(item.get("quantity", 0))
                validated.append({
                    "product": real["name"],
                    "product_id": real["id"],
                    "quantity": qty,
                    "unit": real["unit"],
                    "unit_price": real["unit_price"],
                    "stock_available": float(real["current_stock"]),
                    "exceeds_stock": qty > float(real["current_stock"]),
                })
            else:
                unknown.append(item.get("product"))

        return {
            "intent": parsed.get("intent", "other"),
            "language": parsed.get("language", "en"),
            "products": validated,
            "unit_mismatch": parsed.get("unit_mismatch", []),
            "unknown": unknown,
        }
    except Exception as e:
        return {
            "intent": "other",
            "language": "en",
            "products": [],
            "unit_mismatch": [],
            "unknown": [],
            "error": str(e),
        }


# ---- CHANGED: responder prompt tightened to never contradict the data ----
RESPONDER_PROMPT = """You are DukaanAI — a friendly shopkeeper's assistant at a small neighbourhood store.

LANGUAGE RULES:
1. Reply in the SAME language as the customer (English → English, Roman Urdu → Roman Urdu, Urdu → Urdu).

STYLE RULES:
2. Be warm, brief, human. 1–4 short sentences.
3. Use ONLY the facts provided in the data below. NEVER invent prices, stock, or product names.
4. NEVER say "I don't have information" if data is provided — always use it.
5. NEVER mention AI / LLM.
6. If the customer requested more than the available stock, clearly say the available amount and ask what they'd like.
7. If a unit mismatch is reported, politely explain how the item is sold (in the catalog unit) and ask the customer to rephrase in that unit.
8. No emojis unless the customer used one.

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
            max_tokens=500,
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return _fallback_reply(intent, data, language)


def _fallback_reply(intent, data, language):
    is_ur = language in ("ur_roman", "ur")

    if intent == "greeting":
        return "Assalam-o-Alaikum! Kya chahiye?" if is_ur else "Hi! How can I help you?"

    if intent == "unit_mismatch":
        m = data.get("mismatch", {})
        return (
            f"Maaf kijiye, {m.get('product')} {m.get('catalog_unit')} mein bikta hai — "
            f"aap {m.get('catalog_unit')} mein bata dein."
            if is_ur else
            f"Sorry, {m.get('product')} is sold by {m.get('catalog_unit')}. "
            f"Could you tell me the quantity in {m.get('catalog_unit')}?"
        )

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

    if intent == "stock_exceeded":
        m = data.get("mismatch", {})
        return (
            f"Sirf {m.get('stock')} {m.get('unit')} {m.get('product')} bacha hai — "
            f"aap ne {m.get('requested')} {m.get('unit')} maanga. Kitna chahiye?"
            if is_ur else
            f"Only {m.get('stock')} {m.get('unit')} of {m.get('product')} available — "
            f"you asked for {m.get('requested')} {m.get('unit')}. How much would you like?"
        )

    if intent == "product_query" and data.get("product"):
        p = data["product"]
        return (
            f"Haan, {p['name']} available hai — Rs.{p['unit_price']} per {p['unit']}, "
            f"{p['stock']} {p['unit']} bacha hai."
            if is_ur else
            f"Yes, {p['name']} is available at Rs.{p['unit_price']} per {p['unit']} — "
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
        total = data.get("draft_total", 0)
        first = data["added_items"][0]
        return (
            f"Theek hai, {first['qty']} {first['unit']} {first['name']} add kar diya. "
            f"Total ab Rs.{total} hai."
            if is_ur else
            f"Added {first['qty']} {first['unit']} of {first['name']}. Running total: Rs.{total}."
        )

    if intent == "confirm":
        return "Confirm karne ke liye neeche Confirm Order button dabaiye." if is_ur else \
               "Click 'Confirm Order' below to place it."

    return "Dobara bata dein?" if is_ur else "Could you say that again?"


# ---------------------------------------------------------------
# Legacy wrapper
# ---------------------------------------------------------------
def parse_order(message: str) -> dict:
    result = classify_message(message)
    return {
        "items": [p for p in result["products"] if p["quantity"] > 0],
        "unknown": result.get("unknown", []),
    }
