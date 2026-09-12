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
# Intent classification + product extraction (single LLM call)
# ---------------------------------------------------------------
CLASSIFIER_PROMPT = """You are the intent classifier for DukaanAI, an AI shop assistant.

Classify the customer's message into ONE of these intents:
- "greeting"      → hello, hi, salam, assalam, hey
- "product_query" → asking about availability/price/stock of a product
- "order_intent"  → wants to order one or more products with quantities
- "confirm"       → yes, haan, ok, confirm, theek hai
- "cancel"        → no, nahi, cancel, chhoro
- "other"         → anything else

Also extract:
- "products": list of {product, quantity, unit} from catalog — only for order_intent or product_query
- "language": "en" | "ur_roman" | "ur" (detect from the message)

CATALOG:
{catalog}

OUTPUT (strict JSON, no markdown):
{{
  "intent": "greeting",
  "language": "ur_roman",
  "products": []
}}

EXAMPLES:
"hi"                     → {{"intent":"greeting","language":"en","products":[]}}
"salam"                  → {{"intent":"greeting","language":"ur_roman","products":[]}}
"milk available hai?"    → {{"intent":"product_query","language":"ur_roman","products":[{{"product":"Milk","quantity":0,"unit":"litre"}}]}}
"atta ka rate?"          → {{"intent":"product_query","language":"ur_roman","products":[{{"product":"Atta","quantity":0,"unit":"kg"}}]}}
"2kg atta, 1 dozen eggs" → {{"intent":"order_intent","language":"ur_roman","products":[{{"product":"Atta","quantity":2,"unit":"kg"}},{{"product":"Eggs","quantity":1,"unit":"dozen"}}]}}
"haan"                   → {{"intent":"confirm","language":"ur_roman","products":[]}}
"no"                     → {{"intent":"cancel","language":"en","products":[]}}
"""


def classify_message(message: str) -> dict:
    """Returns {intent, language, products}. Validates against real DB."""
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

        # Validate extracted products against DB
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
# Natural-language response generator (shopkeeper voice)
# ---------------------------------------------------------------
RESPONDER_PROMPT = """You are DukaanAI — a friendly shopkeeper's assistant at a small neighbourhood store.

RULES:
1. Reply in the SAME language as the customer. If they wrote English, reply in English. If Roman Urdu, reply in Roman Urdu. If Urdu script, reply in Urdu script.
2. Be warm, brief, and human — like a real shopkeeper talking to a regular customer.
3. Use ONLY the facts provided below. NEVER invent prices, stock, or product names.
4. NEVER mention that you are an AI or LLM.
5. Keep replies to 1–3 short sentences. No emojis unless the customer uses them.
6. If confirming an order summary, list the items naturally (e.g., "5 litre doodh, total Rs.1050").

FACTUAL DATA (use exactly as given):
{data}

RESPOND TO CUSTOMER IN THEIR LANGUAGE. Output plain text only, no JSON, no markdown fences.
"""


def generate_reply(customer_message: str, intent: str, data: dict, language: str) -> str:
    """Generates a natural shopkeeper reply given structured facts from the DB."""
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
                {"role": "user", "content": f"{lang_hint}\n\nCustomer said: {customer_message}\nIntent: {intent}"},
            ],
            temperature=0.6,
            max_tokens=300,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        # Safe fallback if the LLM fails
        return _fallback_reply(intent, data, language)


def _fallback_reply(intent, data, language):
    """Deterministic replies if LLM call fails — keeps chat usable."""
    if intent == "greeting":
        return "Hi! How can I help you?" if language == "en" else "Assalam-o-Alaikum! Kya chahiye?"
    if intent == "product_query" and data.get("product"):
        p = data["product"]
        return f"{p['name']} available hai — Rs.{p['unit_price']} per {p['unit']}, {p['stock']} {p['unit']} bacha hai."
    if intent == "order_intent" and data.get("items"):
        total = data.get("total", 0)
        return f"Order ready hai — total Rs.{total}. Confirm karein?"
    if intent == "confirm":
        return "Shukriya! Order confirm ho gaya."
    return "Samajh nahi paya, dobara bata dein?"


# ---------------------------------------------------------------
# Keep parse_order for backward compatibility with old tests
# ---------------------------------------------------------------
def parse_order(message: str) -> dict:
    """Legacy wrapper — used by tests/test_phase2.py."""
    result = classify_message(message)
    return {
        "items": [p for p in result["products"] if p["quantity"] > 0],
        "unknown": result.get("unknown", []),
    }
