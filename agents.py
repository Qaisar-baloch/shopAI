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


# ---------------------------------------------------------------
# Product catalog for the LLM
# ---------------------------------------------------------------
def get_product_catalog():
    products = list_products()
    return [
        {"name": p["name"], "aliases": p["aliases"], "unit": p["unit"]}
        for p in products
    ]


# ---------------------------------------------------------------
# Intent classifier (expanded)
# ---------------------------------------------------------------
CLASSIFIER_PROMPT = """You are the intent classifier for DukaanAI, an AI shop assistant.

Classify the customer's message into EXACTLY ONE of these intents:

- "greeting"         → hi, hello, salam, assalam, hey, aoaa
- "product_query"    → asks about availability/price/stock of a SPECIFIC product
- "inventory_query"  → asks what products exist in the shop, wants a LIST, "kya kya hai", "what do you have", "show inventory", "stock me kia hai", "all items", "menu"
- "price_query"      → asks about price ONLY of a specific product ("rate kya hai", "kitne ka hai")
- "order_intent"     → wants to order one or more products WITH quantities
- "confirm"          → yes, haan, ok, confirm, theek hai
- "cancel"           → no, nahi, cancel, chhoro
- "other"            → anything else

Also extract:
- "products": list of {product, quantity, unit} from catalog (for product_query, price_query, order_intent). For inventory_query, leave empty.
- "language": "en" | "ur_roman" | "ur"

CATALOG:
{catalog}

OUTPUT (strict JSON, no markdown):
{{
  "intent": "product_query",
  "language": "ur_roman",
  "products": [{{"product":"Milk","quantity":0,"unit":"litre"}}]
}}

EXAMPLES:
"hi"                              → {{"intent":"greeting","language":"en","products":[]}}
"salam"                           → {{"intent":"greeting","language":"ur_roman","products":[]}}
"milk available hai?"             → {{"intent":"product_query","language":"ur_roman","products":[{{"product":"Milk","quantity":0,"unit":"litre"}}]}}
"atta ka rate?"                   → {{"intent":"price_query","language":"ur_roman","products":[{{"product":"Atta","quantity":0,"unit":"kg"}}]}}
"stock me kia kia hai?"           → {{"intent":"inventory_query","language":"ur_roman","products":[]}}
"what do you have?"               → {{"intent":"inventory_query","language":"en","products":[]}}
"show me everything"              → {{"intent":"inventory_query","language":"en","products":[]}}
"kya kya items hain"              → {{"intent":"inventory_query","language":"ur_roman","products":[]}}
"2kg atta, 1 dozen eggs"          → {{"intent":"order_intent","language":"ur_roman","products":[{{"product":"Atta","quantity":2,"unit":"kg"}},{{"product":"Eggs","quantity":1,"unit":"dozen"}}]}}
"haan"                            → {{"intent":"confirm","language":"ur_roman","products":[]}}
"no"                              → {{"intent":"cancel","language":"en","products":[]}}
"""


def classify_message(message: str) -> dict:
    """Returns {intent, language, products, unknown}."""
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
                validated.append({
                    "product": real["name"],
                    "product_id": real["id"],
                    "quantity": float(item.get("quantity", 0)),
                    "unit": real["unit"],
                    "unit_price": real["unit_price"],
                })
            else:
                unknown.append(item.get("product"))

        return {
            "intent": parsed.get("intent", "other"),
            "language": parsed.get("language", "en"),
            "products": validated,
            "unknown": unknown,
        }
    except Exception as e:
        return {
            "intent": "other",
            "language": "en",
            "products": [],
            "unknown": [],
            "error": str(e),
        }


# ---------------------------------------------------------------
# Natural-language response generator
# ---------------------------------------------------------------
RESPONDER_PROMPT = """You are DukaanAI — a friendly shopkeeper's assistant at a small neighbourhood store.

LANGUAGE RULES:
1. Reply in the SAME language as the customer. English → English. Roman Urdu → Roman Urdu. Urdu script → Urdu script.
2. Never mix languages unless the customer mixed them.

STYLE RULES:
3. Be warm, brief, and human — like a real shopkeeper talking to a regular customer.
4. Keep replies to 1–4 short sentences. Use short paragraphs or bullet points when listing multiple items.
5. Use ONLY the facts provided below. NEVER invent prices, stock, or product names.
6. NEVER say "I don't have information" if there is data below — always give what you have.
7. NEVER mention that you are an AI or LLM.
8. If asked a broad question ("what else do you have"), list ALL items provided in the data — one per line, with price.
9. Do NOT use emojis unless the customer did.

FACTUAL DATA (authoritative — quote exactly):
{data}

Output plain text only. No JSON. No markdown code fences.
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
                {
                    "role": "system",
                    "content": prompt,
                },
                {
                    "role": "user",
                    "content": f"{lang_hint}\n\nCustomer said: {customer_message}\nDetected intent: {intent}",
                },
            ],
            temperature=0.6,
            max_tokens=500,
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return _fallback_reply(intent, data, language)


def _fallback_reply(intent, data, language):
    """Deterministic fallback if LLM call fails."""
    is_ur = language in ("ur_roman", "ur")

    if intent == "greeting":
        return "Assalam-o-Alaikum! Kya chahiye?" if is_ur else "Hi! How can I help you?"

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
            f"Haan, {p['name']} available hai — Rs.{p['unit_price']} per {p['unit']}, "
            f"{p['stock']} {p['unit']} bacha hai."
            if is_ur else
            f"Yes, we have {p['name']} at Rs.{p['unit_price']} per {p['unit']} — "
            f"{p['stock']} {p['unit']} available."
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
        return (
            f"Theek hai, {data['added_items'][0]['qty']} {data['added_items'][0]['unit']} "
            f"{data['added_items'][0]['name']} add kar diya. Total ab Rs.{total} hai."
            if is_ur else
            f"Added to your order. Running total: Rs.{total}."
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
