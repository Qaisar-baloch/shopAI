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
        raise ValueError("GROQ_API_KEY not found or invalid.")
    return Groq(api_key=api_key)


DIVISIBLE_UNITS = {"kg", "gram", "litre", "ml"}
INDIVISIBLE_UNITS = {"piece", "dozen", "bag", "pack", "packet", "bottle"}

ALIAS_HINTS = {
    "atta": "atta", "aata": "atta", "flour": "atta",
    "chawal": "rice", "rice": "rice", "basmati": "rice",
    "doodh": "milk", "milk": "milk", "dudh": "milk",
    "anday": "eggs", "anda": "eggs", "egg": "eggs", "eggs": "eggs",
    "cheeni": "sugar", "sugar": "sugar", "shakar": "sugar", "shakkar": "sugar",
    "namak": "salt", "salt": "salt",
    "tel": "oil", "oil": "oil",
    "patti": "tea", "chai": "tea", "tea": "tea",
    "bread": "bread", "roti": "bread",
    "sabun": "soap", "soap": "soap",
    "pani": "water", "water": "water",
    "chips": "lays", "lays": "lays", "kurkure": "kurkure",
    "biscuit": "biscuit", "biscuits": "biscuit",
    "shampoo": "shampoo",
    "cheese": "cheese", "paneer": "cheese",
    "butter": "butter", "makhan": "butter",
    "yogurt": "yogurt", "dahi": "yogurt",
    "dalda": "dalda", "ghee": "dalda",
    "cream": "cream", "balai": "cream", "malai": "cream",
    "bun": "bun", "rusk": "rusk",
    "surf": "surf", "ariel": "ariel",
    "lux": "lux", "lifebuoy": "lifebuoy", "safeguard": "safeguard",
    "pantene": "pantene", "colgate": "colgate",
    "coca": "coca", "coke": "coca", "cola": "coca",
    "pepsi": "pepsi", "sprite": "sprite", "fanta": "fanta",
    "slice": "slice", "sooper": "sooper", "oreo": "oreo",
    "olive": "olive", "turmeric": "turmeric", "haldi": "turmeric",
    "cumin": "cumin", "zeera": "cumin", "jeera": "cumin",
    "garam": "garam",
}


def _fmt_num(x):
    """Format a number cleanly: 350.0 → '350', 0.29 → '0.29'."""
    try:
        if float(x).is_integer():
            return str(int(x))
    except (ValueError, TypeError):
        pass
    return f"{x:g}" if isinstance(x, (int, float)) else str(x)


def _extract_sku_size(product_name):
    name = product_name.lower()
    m = re.search(
        r"(\d+(?:\.\d+)?)\s*(kg|kgs|g|gram|grams|litre|liter|ltr|l|ml|pcs|pc|piece|pieces|dozen|pack|packet|bag|bottle)",
        name,
    )
    if not m:
        return None, None
    size = float(m.group(1))
    raw = m.group(2)
    if raw in ("kg", "kgs"):
        return size, "kg"
    if raw in ("g", "gram", "grams"):
        return size / 1000.0, "kg"
    if raw in ("l", "litre", "liter", "ltr"):
        return size, "litre"
    if raw == "ml":
        return size / 1000.0, "litre"
    if raw in ("pcs", "pc", "piece", "pieces"):
        return size, "piece"
    if raw == "dozen":
        return size, "dozen"
    if raw in ("pack", "packet"):
        return size, "pack"
    if raw == "bag":
        return size, "bag"
    if raw == "bottle":
        return size, "bottle"
    return None, None


def _normalize_unit(unit):
    if not unit:
        return None
    u = unit.lower().strip()
    if u in ("kilo", "kilos", "kg", "kgs", "kilogram", "kilograms"):
        return "kg"
    if u in ("g", "gram", "grams"):
        return "kg"
    if u in ("liter", "litre", "ltr", "l", "liters", "litres"):
        return "litre"
    if u in ("ml", "milliliter", "millilitre"):
        return "litre"
    if u in ("pc", "pcs", "piece", "pieces"):
        return "piece"
    if u == "dozen":
        return "dozen"
    if u in ("pack", "packet", "packets", "packs"):
        return "pack"
    if u == "bag":
        return "bag"
    if u == "bottle":
        return "bottle"
    return u


def _resolve_sku(product_fragment, requested_qty, user_unit):
    """
    Find the best matching SKU for a fragment + quantity + unit.
    Considers ALL products whose name matches the fragment (not just the first).
    """
    products = list_products()
    fragment = product_fragment.lower()

    # 1. Expand via alias ("aata" → "atta")
    search_term = ALIAS_HINTS.get(fragment, fragment)

    # 2. Build candidate list from ALL products whose name contains search_term
    matches = [p for p in products if search_term in p["name"].lower()]

    # 3. If empty, try direct find_product
    if not matches:
        direct = find_product(product_fragment)
        if direct:
            matches = [direct]

    if not matches:
        return None, None, None

    user_unit_norm = _normalize_unit(user_unit)

    if user_unit_norm in ("kg", "litre") and requested_qty:
        if user_unit_norm == "kg":
            target_base = requested_qty if (user_unit or "").lower() not in ("g", "gram", "grams") else requested_qty / 1000.0
        else:
            target_base = requested_qty if (user_unit or "").lower() != "ml" else requested_qty / 1000.0

        # Look for SKU whose size matches user's quantity
        best_exact = None
        for p in matches:
            size, base = _extract_sku_size(p["name"])
            if base and base == user_unit_norm and size and abs(size - target_base) < 0.1:
                best_exact = p
                break
        if best_exact:
            return best_exact, 1.0, f"{best_exact['name']}"

        # No exact size — use smallest SKU, compute quantity
        smallest = None
        smallest_size = None
        for p in matches:
            size, base = _extract_sku_size(p["name"])
            if base and base == user_unit_norm and size:
                if smallest_size is None or size < smallest_size:
                    smallest = p
                    smallest_size = size
        if smallest:
            import math
            qty = math.ceil(target_base / smallest_size)
            note = f"{qty} × {smallest['name']} ({smallest_size}{user_unit_norm} each)"
            return smallest, float(qty), note

        return matches[0], requested_qty, None

    if user_unit_norm:
        for p in matches:
            if p["unit"].lower() == user_unit_norm:
                if user_unit_norm in INDIVISIBLE_UNITS and requested_qty and requested_qty < 1:
                    return p, 1.0, f"rounded up to 1 {p['unit']} of {p['name']}"
                return p, float(requested_qty) if requested_qty else 1.0, None

    return matches[0], float(requested_qty) if requested_qty else 1.0, None


# ---------------------------------------------------------------
# Local parser
# ---------------------------------------------------------------
def _local_parse(message: str) -> dict:
    msg = message.lower().strip()
    products = []
    spend_orders = []
    unknown = []
    seen_ids = set()

    # ---------- Spend orders ----------
    spend_pattern = re.compile(
        r"(\d+)\s*(?:rs\.?|rupay[ae]?|pkr|rupees?|ka|ke|ki|of)\s+([a-z]+)",
        re.IGNORECASE,
    )
    for m in spend_pattern.finditer(msg):
        amount = float(m.group(1))
        word = m.group(2).lower()
        real = find_product(word) or find_product(ALIAS_HINTS.get(word, ""))
        if real and real["id"] not in seen_ids:
            seen_ids.add(real["id"])
            up = float(real["unit_price"])
            full = int(amount // up) if up > 0 else 0
            frac = round(amount / up, 2)
            left = round(amount - full * up, 2)
            is_div = real["unit"].lower() in DIVISIBLE_UNITS
            fulfilment = "fraction" if is_div else ("full_units_with_leftover" if full >= 1 else "insufficient")
            spend_orders.append({
                "product": real["name"],
                "product_id": real["id"],
                "amount": amount,
                "unit": real["unit"],
                "unit_price": up,
                "computed_quantity": frac if is_div else full,
                "fulfilment": fulfilment,
                "full_units": full,
                "leftover": left,
                "stock_available": float(real["current_stock"]),
                "exceeds_stock": (frac if is_div else full) > float(real["current_stock"]),
            })

    # ---------- Quantity orders ----------
    FRACTIONS = {"half": 0.5, "aadha": 0.5, "adha": 0.5, "quarter": 0.25, "pao": 0.25}
    qty_pattern = re.compile(
        r"(\d+(?:\.\d+)?|half|aadha|adha|quarter|pao)\s*"
        r"(kg|kgs|kilo|kilos|gram|grams|g|"
        r"litre|liter|ltr|l|ml|"
        r"dozen|piece|pieces|pcs|pc|"
        r"pack|packet|packs|bag|bottle)?\s+"
        r"([a-z]+)",
        re.IGNORECASE,
    )
    for m in qty_pattern.finditer(msg):
        raw_qty = m.group(1).lower()
        qty = FRACTIONS.get(raw_qty)
        if qty is None:
            try:
                qty = float(raw_qty)
            except ValueError:
                continue
        unit_raw = m.group(2)
        word = m.group(3).lower()

        if word in ("rs", "rs.", "rupay", "pkr", "rupees", "ka", "ke", "ki", "of"):
            continue

        resolved, adjusted_qty, note = _resolve_sku(word, qty, unit_raw)
        if resolved and resolved["id"] not in seen_ids:
            seen_ids.add(resolved["id"])
            products.append({
                "product": resolved["name"],
                "product_id": resolved["id"],
                "quantity": adjusted_qty,
                "unit": resolved["unit"],
                "unit_price": float(resolved["unit_price"]),
                "stock_available": float(resolved["current_stock"]),
                "exceeds_stock": adjusted_qty > float(resolved["current_stock"]),
                "note": note,
            })

    # ---------- Bare product name fallback ----------
    if not products and not spend_orders:
        stopwords = {
            "the", "and", "for", "with", "have", "want", "need", "please",
            "give", "some", "hai", "kya", "ka", "ke", "ki", "aur", "chahiye",
            "dedo", "hain", "mein", "se", "par", "salam", "salaam", "assalam",
            "assalamu", "asalam", "alaikum", "allaikum", "u", "o", "aliakum",
            "hello", "hi", "hey", "aoaa", "kia", "bol", "rahe", "ho", "kyun",
        }
        for w in re.findall(r"\b([a-z]{3,})\b", msg):
            if w in stopwords:
                continue
            real = find_product(w) or find_product(ALIAS_HINTS.get(w, ""))
            if real and real["id"] not in seen_ids:
                seen_ids.add(real["id"])
                products.append({
                    "product": real["name"],
                    "product_id": real["id"],
                    "quantity": 1.0,
                    "unit": real["unit"],
                    "unit_price": float(real["unit_price"]),
                    "stock_available": float(real["current_stock"]),
                    "exceeds_stock": False,
                    "note": "assumed 1",
                })
                break

    # ---------- Intent inference ----------
    greeting_words = ("salam", "salaam", "assalam", "assalamu", "asalam", "aoaa",
                      "hello", "hi", "hey")
    inventory_phrases = (
        "stock", "inventory", "kya kya", "kia kia", "kia kya", "kya kia",
        "kia kiya", "kya kiya", "aur kia", "aur kya", "sab kuch",
        "show me", "list all", "menu", "dikhao", "dikha do", "available items",
        "what do you have", "what have you got",
    )

    if products or spend_orders:
        intent = "spend_based_order" if (spend_orders and not products) else "order_intent"
    elif any(w in msg for w in greeting_words) and len(msg.split()) <= 5:
        intent = "greeting"
    elif any(p in msg for p in inventory_phrases):
        intent = "inventory_query"
    elif any(w in msg for w in ("yes", "haan", "ok", "confirm", "theek")):
        intent = "confirm"
    elif any(w in msg for w in ("no", "nahi", "cancel", "chhoro")):
        intent = "cancel"
    elif any(w in msg for w in ("available", "kitne", "rate", "price", "how much")):
        intent = "product_query"
    else:
        intent = "other"

    # ---------- Language detection ----------
    ur_words = (
        "hai", "kya", "kia", "ka", "ke", "ki", "aur", "chahiye", "dedo", "hain",
        "mein", "kaisa", "salam", "salaam", "assalam", "assalamu", "asalam",
        "alaikum", "allaikum", "aliakum", "bhai", "aap", "tum", "mujhe", "aapko",
        "do", "de", "dena", "lena", "kro", "karo", "bol", "rahe",
    )
    language = "ur_roman" if any(w in msg for w in ur_words) else "en"

    return {
        "intent": intent,
        "language": language,
        "products": products,
        "spend_orders": spend_orders,
        "unit_mismatch": [],
        "unknown": unknown,
        "_source": "local",
    }


# ---------------------------------------------------------------
# Optional Groq enhancement
# ---------------------------------------------------------------
CLASSIFIER_PROMPT = """Classify customer message for a kiryana shop.
Return JSON: {"intent":"...","language":"en","products":[],"spend_orders":[],"unit_mismatch":[],"unknown":[]}
Intents: greeting, product_query, inventory_query, price_query, order_intent, spend_based_order, confirm, cancel, other.
"""


def _groq_parse(message: str):
    try:
        client = get_client()
        resp = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {"role": "system", "content": CLASSIFIER_PROMPT},
                {"role": "user", "content": message},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=250,
        )
        return json.loads(resp.choices[0].message.content)
    except Exception:
        return None


def classify_message(message: str) -> dict:
    local = _local_parse(message)
    if local["products"] or local["spend_orders"] or local["intent"] != "other":
        return local

    groq_result = _groq_parse(message)
    if groq_result and (groq_result.get("products") or groq_result.get("spend_orders") or groq_result.get("unknown")):
        return {
            "intent": groq_result.get("intent", local["intent"]),
            "language": groq_result.get("language", local["language"]),
            "products": groq_result.get("products", []),
            "spend_orders": groq_result.get("spend_orders", []),
            "unit_mismatch": groq_result.get("unit_mismatch", []),
            "unknown": groq_result.get("unknown", []),
            "_source": "groq",
        }
    return local


# ---------------------------------------------------------------
# Reply generator
# ---------------------------------------------------------------
RESPONDER_PROMPT = """You are DukaanAI — a friendly kiryana shop assistant in Pakistan.
CURRENCY: always "Rs." (never ₹ or $).
LANGUAGE: reply in the customer's language.
RULES:
- Warm, brief. 1-4 sentences.
- Use ONLY facts in data. Never invent.
- No emojis unless the customer used one.
DATA:
{data}
Plain text only.
"""


def generate_reply(customer_message: str, intent: str, data: dict, language: str) -> str:
    deterministic = _deterministic_reply(intent, data, language)
    if deterministic:
        return deterministic

    try:
        client = get_client()
        prompt = RESPONDER_PROMPT.replace("{data}", json.dumps(data, indent=2, ensure_ascii=False))
        resp = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"{customer_message}\nIntent: {intent}"},
            ],
            temperature=0.4,
            max_tokens=400,
        )
        text = resp.choices[0].message.content.strip()
        return text.replace("₹", "Rs.").replace("$", "Rs.")
    except Exception:
        return _fallback_reply(intent, data, language)


def _deterministic_reply(intent, data, language):
    is_ur = language in ("ur_roman", "ur")

    if intent == "greeting":
        return "Walaikum assalam! Kya chahiye?" if is_ur else "Hi! How can I help you?"

    if intent == "order_intent" and data.get("added_items"):
        parts = [f"{_fmt_num(a['qty'])} {a['unit']} {a['name']}" for a in data["added_items"]]
        total = data.get("draft_total", 0)
        return (
            f"Theek hai, add kar diya: {', '.join(parts)}. Total: Rs.{_fmt_num(total)}."
            if is_ur else
            f"Added: {', '.join(parts)}. Running total: Rs.{_fmt_num(total)}."
        )

    if intent == "spend_based_order":
        orders = data.get("spend_orders", [])
        if not orders:
            return None
        lines = []
        any_actionable = False
        for o in orders:
            f = o.get("fulfilment")
            amount = _fmt_num(o["amount"])
            price = _fmt_num(o["unit_price"])
            if f == "fraction":
                any_actionable = True
                lines.append(
                    f"Rs.{amount} mein {_fmt_num(o['computed_quantity'])} {o['unit']} "
                    f"{o['product']} milega (Rs.{price}/{o['unit']})."
                    if is_ur else
                    f"Rs.{amount} = {_fmt_num(o['computed_quantity'])} {o['unit']} of "
                    f"{o['product']} (Rs.{price}/{o['unit']})."
                )
            elif f == "full_units_with_leftover":
                any_actionable = True
                lines.append(
                    f"Rs.{amount} mein {_fmt_num(o['full_units'])} {o['unit']} "
                    f"{o['product']} (Rs.{price} each), Rs.{_fmt_num(o['leftover'])} bachega."
                    if is_ur else
                    f"Rs.{amount} = {_fmt_num(o['full_units'])} {o['unit']} of "
                    f"{o['product']} (Rs.{price} each), Rs.{_fmt_num(o['leftover'])} leftover."
                )
            else:  # insufficient
                lines.append(
                    f"Rs.{amount} mein ek {o['unit']} bhi nahi milta — ek {o['unit']} Rs.{price} hai."
                    if is_ur else
                    f"Rs.{amount} isn't enough for one {o['unit']} — one {o['unit']} costs Rs.{price}."
                )
        if any_actionable:
            tail = " Confirm karein?" if is_ur else " Confirm?"
            return " ".join(lines) + tail
        return " ".join(lines)

    return None


def _fallback_reply(intent, data, language):
    is_ur = language in ("ur_roman", "ur")

    if intent == "greeting":
        return "Walaikum assalam! Kya chahiye?" if is_ur else "Hi! How can I help you?"

    if intent == "spend_based_order":
        orders = data.get("spend_orders", [])
        if not orders:
            return "Samajh nahi paya." if is_ur else "Couldn't understand."
        parts = []
        for o in orders:
            if o.get("fulfilment") == "fraction":
                parts.append(f"Rs.{_fmt_num(o['amount'])} = {_fmt_num(o['computed_quantity'])} {o['unit']} {o['product']}")
            elif o.get("fulfilment") == "full_units_with_leftover":
                parts.append(f"Rs.{_fmt_num(o['amount'])} = {_fmt_num(o['full_units'])} {o['unit']} {o['product']}")
            else:
                parts.append(f"Rs.{_fmt_num(o['amount'])} insufficient for {o['product']}")
        return " | ".join(parts)

    if intent == "inventory_query":
        items = data.get("all_items", [])
        if not items:
            return "Stock khali hai." if is_ur else "Shop is empty."
        lines = [
            f"- {it['name']}: Rs.{_fmt_num(it['unit_price'])}/{it['unit']} "
            f"({_fmt_num(it['stock'])} available)"
            for it in items[:20]
        ]
        header = "Yeh items available hain:" if is_ur else "Items available:"
        return header + "\n" + "\n".join(lines)

    if intent == "order_intent" and data.get("added_items"):
        parts = [f"{_fmt_num(a['qty'])} {a['unit']} {a['name']}" for a in data["added_items"]]
        return f"Added: {', '.join(parts)}."

    return "Dobara bata dein? Jaise: '2kg atta' ya '100 ka tel'." if is_ur \
           else "Say that again? Like: '2kg atta' or '100 ka tel'."


def parse_order(message: str) -> dict:
    result = classify_message(message)
    return {
        "items": [p for p in result["products"] if p["quantity"] > 0],
        "unknown": result.get("unknown", []),
    }
