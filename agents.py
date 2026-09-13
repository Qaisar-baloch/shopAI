import os
import json
import re
import time
import functools
from groq import Groq, RateLimitError
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


# ---------------------------------------------------------------
# Rate-limit aware Groq wrapper
# ---------------------------------------------------------------
class GroqUnavailable(Exception):
    """Raised when Groq can't serve a request (rate limit, auth, network)."""
    def __init__(self, message, retry_seconds=None, kind="unavailable"):
        super().__init__(message)
        self.retry_seconds = retry_seconds
        self.kind = kind


def _call_groq(messages, max_tokens=300, temperature=0.3):
    """
    Wrapper around Groq chat.completions.create that translates
    failures into GroqUnavailable with useful metadata.
    """
    try:
        client = get_client()
        resp = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=messages,
            response_format={"type": "json_object"} if "JSON" in messages[0]["content"][:200] else None,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content
    except RateLimitError as e:
        # Try to extract "try again in Xs" from Groq's error message
        retry_s = None
        msg = str(e)
        m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", msg)
        if m:
            minutes = float(m.group(1)) if m.group(1) else 0
            seconds = float(m.group(2))
            retry_s = int(minutes * 60 + seconds)
        raise GroqUnavailable(
            "Daily token quota reached for the AI service.",
            retry_seconds=retry_s,
            kind="rate_limit",
        ) from e
    except Exception as e:
        raise GroqUnavailable(
            f"AI service temporarily unavailable: {str(e)[:120]}",
            kind="error",
        ) from e


# ---------------------------------------------------------------
# Local parser (no API calls — handles most orders)
# ---------------------------------------------------------------
DIVISIBLE_UNITS = {"kg", "gram", "litre", "ml"}

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
    table = {
        "kg": ("kg", 1.0), "kgs": ("kg", 1.0),
        "g": ("kg", 0.001), "gram": ("kg", 0.001), "grams": ("kg", 0.001),
        "l": ("litre", 1.0), "litre": ("litre", 1.0),
        "liter": ("litre", 1.0), "ltr": ("litre", 1.0),
        "ml": ("litre", 0.001),
        "pcs": ("piece", 1.0), "pc": ("piece", 1.0),
        "piece": ("piece", 1.0), "pieces": ("piece", 1.0),
        "dozen": ("dozen", 1.0),
        "pack": ("pack", 1.0), "packet": ("pack", 1.0),
        "bag": ("bag", 1.0),
        "bottle": ("bottle", 1.0),
    }
    if raw in table:
        base, mult = table[raw]
        return size * mult, base
    return None, None


def _normalize_unit(unit):
    if not unit:
        return None
    u = unit.lower().strip()
    mapping = {
        "kilo": "kg", "kilos": "kg", "kg": "kg", "kgs": "kg",
        "kilogram": "kg", "kilograms": "kg",
        "g": "gram", "gram": "gram", "grams": "gram",
        "liter": "litre", "litre": "litre", "ltr": "litre", "l": "litre",
        "liters": "litre", "litres": "litre",
        "ml": "ml", "milliliter": "ml", "millilitre": "ml",
        "pc": "piece", "pcs": "piece", "piece": "piece", "pieces": "piece",
        "dozen": "dozen",
        "pack": "pack", "packet": "pack", "packets": "pack", "packs": "pack",
        "bag": "bag", "bags": "bag",
        "bottle": "bottle", "bottles": "bottle",
    }
    return mapping.get(u, u)


def _product_family_matches(fragment):
    products = list_products()
    fragment_l = fragment.lower()
    search_term = ALIAS_HINTS.get(fragment_l, fragment_l)
    matches = [p for p in products if search_term in p["name"].lower()]
    if not matches:
        direct = find_product(fragment)
        if direct:
            matches = [direct]
    return matches


def _family_label(fragment, matches):
    if not matches:
        return fragment
    first = matches[0]["name"]
    cleaned = re.sub(r"\s*\d+.*$", "", first).strip()
    return cleaned or first


def _resolve_request(fragment, qty, user_unit):
    matches = _product_family_matches(fragment)
    if not matches:
        return {"status": "not_found"}

    user_unit_norm = _normalize_unit(user_unit)
    qty = float(qty) if qty else 1.0

    if user_unit_norm:
        # Same unit as a SKU's own unit (e.g. "dozen eggs" where Eggs is by dozen)
        for p in matches:
            if p["unit"].lower() == user_unit_norm:
                return {"status": "ok", "product": p, "quantity": qty}

        # Divisible units — look for SKU whose name size == qty
        if user_unit_norm in DIVISIBLE_UNITS:
            for p in matches:
                size, base = _extract_sku_size(p["name"])
                if base == user_unit_norm and size is not None and abs(size - qty) < 0.05:
                    return {"status": "ok", "product": p, "quantity": 1.0}

            # Size hint in SKU name matches qty regardless of unit (e.g. "12 eggs")
            for p in matches:
                size, _ = _extract_sku_size(p["name"])
                if size is not None and abs(size - qty) < 0.05:
                    return {"status": "ok", "product": p, "quantity": 1.0}

        return {
            "status": "ambiguous",
            "family": _family_label(fragment, matches),
            "requested_qty": qty,
            "requested_unit": user_unit,
            "options": matches,
        }

    if len(matches) == 1:
        p = matches[0]
        return {"status": "ok", "product": p, "quantity": qty}

    return {
        "status": "ambiguous",
        "family": _family_label(fragment, matches),
        "requested_qty": qty,
        "requested_unit": None,
        "options": matches,
    }


def _local_parse(message: str) -> dict:
    msg = message.lower().strip()
    products = []
    ambiguous = []
    spend_orders = []
    unknown = []
    seen_families = set()

    # Spend orders: "100 ka tel"
    spend_pattern = re.compile(
        r"(\d+)\s*(?:rs\.?|rupay[ae]?|pkr|rupees?|ka|ke|ki|of)\s+([a-z]+)",
        re.IGNORECASE,
    )
    for m in spend_pattern.finditer(msg):
        amount = float(m.group(1))
        word = m.group(2).lower()
        real = find_product(word) or find_product(ALIAS_HINTS.get(word, ""))
        if real:
            family = _family_label(word, [real])
            if family in seen_families:
                continue
            seen_families.add(family)
            up = float(real["unit_price"])
            full = int(amount // up) if up > 0 else 0
            frac = round(amount / up, 2)
            left = round(amount - full * up, 2)
            is_div = real["unit"].lower() in DIVISIBLE_UNITS
            spend_orders.append({
                "product": real["name"], "product_id": real["id"],
                "amount": amount, "unit": real["unit"], "unit_price": up,
                "computed_quantity": frac if is_div else full,
                "fulfilment": "fraction" if is_div else
                              ("full_units_with_leftover" if full >= 1 else "insufficient"),
                "full_units": full, "leftover": left,
                "stock_available": float(real["current_stock"]),
                "exceeds_stock": (frac if is_div else full) > float(real["current_stock"]),
            })

    # Quantity orders
    FRACTIONS = {"half": 0.5, "aadha": 0.5, "adha": 0.5, "quarter": 0.25, "pao": 0.25}
    qty_pattern = re.compile(
        r"(\d+(?:\.\d+)?|half|aadha|adha|quarter|pao)\s*"
        r"(kg|kgs|kilo|kilos|kilogram|kilograms|"
        r"gram|grams|g|"
        r"litre|liter|litres|liters|ltr|l|"
        r"ml|dozen|piece|pieces|pcs|pc|"
        r"pack|packet|packs|bag|bags|bottle|bottles)?\s+"
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
        result = _resolve_request(word, qty, unit_raw)
        if result["status"] == "ok":
            p = result["product"]
            if any(x["product_id"] == p["id"] for x in products):
                continue
            products.append({
                "product": p["name"], "product_id": p["id"],
                "quantity": result["quantity"], "unit": p["unit"],
                "unit_price": float(p["unit_price"]),
                "stock_available": float(p["current_stock"]),
                "exceeds_stock": result["quantity"] > float(p["current_stock"]),
            })
        elif result["status"] == "ambiguous":
            family = result["family"].lower()
            if family in seen_families:
                continue
            seen_families.add(family)
            ambiguous.append(result)

    # Bare product name (no qty)
    if not products and not spend_orders and not ambiguous:
        stopwords = {
            "the", "and", "for", "with", "have", "want", "need", "please",
            "give", "some", "hai", "kya", "kia", "ka", "ke", "ki", "aur",
            "chahiye", "dedo", "hain", "mein", "se", "par", "salam", "salaam",
            "assalam", "assalamu", "asalam", "alaikum", "allaikum", "u", "o",
            "aliakum", "hello", "hi", "hey", "aoaa", "bol", "rahe", "ho",
        }
        for w in re.findall(r"\b([a-z]{3,})\b", msg):
            if w in stopwords:
                continue
            matches = _product_family_matches(w)
            if matches:
                if len(matches) == 1:
                    p = matches[0]
                    products.append({
                        "product": p["name"], "product_id": p["id"],
                        "quantity": 1.0, "unit": p["unit"],
                        "unit_price": float(p["unit_price"]),
                        "stock_available": float(p["current_stock"]),
                        "exceeds_stock": False,
                    })
                else:
                    ambiguous.append({
                        "status": "ambiguous",
                        "family": _family_label(w, matches),
                        "requested_qty": 1.0, "requested_unit": None,
                        "options": matches,
                    })
                break

    # Intent detection — always local, zero tokens
    greeting_words = ("salam", "salaam", "assalam", "assalamu", "asalam", "aoaa",
                      "hello", "hi", "hey")
    inventory_phrases = (
        "stock", "inventory", "kya kya", "kia kia", "kia kya", "kya kia",
        "kia kiya", "kya kiya", "aur kia", "aur kya", "sab kuch",
        "show me", "list all", "menu", "dikhao", "dikha do", "available items",
        "what do you have",
    )

    if products or spend_orders or ambiguous:
        if ambiguous and not products and not spend_orders:
            intent = "ambiguous_request"
        elif spend_orders and not products and not ambiguous:
            intent = "spend_based_order"
        else:
            intent = "order_intent"
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

    ur_words = (
        "hai", "kya", "kia", "ka", "ke", "ki", "aur", "chahiye", "dedo", "hain",
        "mein", "kaisa", "salam", "salaam", "assalam", "assalamu", "asalam",
        "alaikum", "allaikum", "aliakum", "bhai", "aap", "tum", "mujhe", "aapko",
        "do", "de", "dena", "lena", "kro", "karo", "bol", "rahe", "wala", "wali",
    )
    language = "ur_roman" if any(w in msg for w in ur_words) else "en"

    return {
        "intent": intent,
        "language": language,
        "products": products,
        "ambiguous": ambiguous,
        "spend_orders": spend_orders,
        "unit_mismatch": [],
        "unknown": unknown,
        "_source": "local",
    }


# ---------------------------------------------------------------
# Slim Groq classifier — only for messages the local parser can't handle
# ---------------------------------------------------------------
SLIM_CLASSIFIER_PROMPT = """Classify the message. Output JSON only.

Intents: greeting, product_query, inventory_query, price_query, order_intent, spend_based_order, confirm, cancel, other.

Format: {"intent":"...","language":"en","products":[],"spend_orders":[],"unknown":[]}
- language: "en" | "ur_roman" | "ur"
- products: [{"product":"<exact name>","quantity":N}]
- spend_orders: [{"product":"<exact name>","amount":N}]

Message: """


def _groq_classify(message: str):
    """Slim classifier — ~250 tokens total. Only used if local parser fails."""
    raw = _call_groq(
        messages=[
            {"role": "system", "content": SLIM_CLASSIFIER_PROMPT},
            {"role": "user", "content": message},
        ],
        max_tokens=200,
        temperature=0.1,
    )
    return json.loads(raw)


# ---------------------------------------------------------------
# Public classifier — local first, Groq only as last resort
# ---------------------------------------------------------------
def classify_message(message: str) -> dict:
    # 1. Try local parser first (zero tokens)
    local = _local_parse(message)

    # If local parser found anything useful, return immediately
    if (local["products"] or local["spend_orders"] or local["ambiguous"]
            or local["intent"] in ("greeting", "inventory_query", "confirm",
                                    "cancel", "product_query", "other")):
        return local

    # 2. Fall back to Groq for genuinely ambiguous messages
    try:
        groq_result = _groq_classify(message)
        # validate products against DB
        validated = []
        unknown = list(groq_result.get("unknown", []))
        for item in groq_result.get("products", []):
            real = find_product(item.get("product", ""))
            if real:
                qty = float(item.get("quantity", 0))
                validated.append({
                    "product": real["name"], "product_id": real["id"],
                    "quantity": qty, "unit": real["unit"],
                    "unit_price": float(real["unit_price"]),
                    "stock_available": float(real["current_stock"]),
                    "exceeds_stock": qty > float(real["current_stock"]),
                })
            else:
                unknown.append(item.get("product"))

        validated_spend = []
        for so in groq_result.get("spend_orders", []):
            real = find_product(so.get("product", ""))
            amount = float(so.get("amount", 0))
            if not real or amount <= 0:
                if not real:
                    unknown.append(so.get("product"))
                continue
            up = float(real["unit_price"])
            full = int(amount // up) if up > 0 else 0
            frac = round(amount / up, 2)
            is_div = real["unit"].lower() in DIVISIBLE_UNITS
            validated_spend.append({
                "product": real["name"], "product_id": real["id"],
                "amount": amount, "unit": real["unit"], "unit_price": up,
                "computed_quantity": frac if is_div else full,
                "fulfilment": "fraction" if is_div else
                              ("full_units_with_leftover" if full >= 1 else "insufficient"),
                "full_units": full,
                "leftover": round(amount - full * up, 2),
                "stock_available": float(real["current_stock"]),
                "exceeds_stock": (frac if is_div else full) > float(real["current_stock"]),
            })

        return {
            "intent": groq_result.get("intent", local["intent"]),
            "language": groq_result.get("language", local["language"]),
            "products": validated,
            "ambiguous": [],
            "spend_orders": validated_spend,
            "unit_mismatch": [],
            "unknown": unknown,
            "_source": "groq",
        }
    except GroqUnavailable as e:
        # Real rate limit — tell the caller so it can show a proper message
        local["_rate_limit"] = {
            "kind": e.kind,
            "retry_seconds": e.retry_seconds,
            "message": str(e),
        }
        return local


# ---------------------------------------------------------------
# Deterministic replies (used before we ever touch Groq)
# ---------------------------------------------------------------
def _fmt_options(options):
    lines = []
    for o in options:
        price = _fmt_num(o["unit_price"])
        lines.append(f"- **{o['name']}** — Rs.{price} per {o['unit']}")
    return "\n".join(lines)


def _ambiguous_reply(ambiguous_list, language, added_items=None):
    is_ur = language in ("ur_roman", "ur")
    chunks = []

    if added_items:
        parts = [f"{_fmt_num(a['qty'])} {a['unit']} {a['name']}" for a in added_items]
        chunks.append(
            f"Theek hai, add kar diya: {', '.join(parts)}." if is_ur
            else f"Added: {', '.join(parts)}."
        )

    for item in ambiguous_list:
        family = item["family"]
        opts = _fmt_options(item["options"])
        req_qty = _fmt_num(item["requested_qty"])
        req_unit = item.get("requested_unit") or ""

        if is_ur:
            if req_unit:
                chunks.append(
                    f"**{family}** {req_unit} mein nahi milta — ye available hai:\n{opts}\n"
                    f"Kaun sa size chahiye?"
                )
            else:
                chunks.append(f"**{family}** ye sizes mein milta hai:\n{opts}\nKaun sa chahiye?")
        else:
            if req_unit:
                chunks.append(
                    f"**{family}** isn't sold by {req_unit} — here's what we have:\n{opts}\n"
                    f"Which size would you like?"
                )
            else:
                chunks.append(f"**{family}** comes in these sizes:\n{opts}\nWhich one?")

    return "\n\n".join(chunks)


def _deterministic_reply(intent, data, language):
    is_ur = language in ("ur_roman", "ur")

    if intent == "greeting":
        return "Walaikum assalam! Kya chahiye?" if is_ur else "Hi! How can I help you?"

    if intent == "ambiguous_request":
        return _ambiguous_reply(data.get("ambiguous", []), language,
                                data.get("added_items"))

    if intent == "order_intent" and data.get("added_items"):
        parts = [f"{_fmt_num(a['qty'])} {a['unit']} {a['name']}" for a in data["added_items"]]
        total = data.get("draft_total", 0)
        base = (
            f"Theek hai, add kar diya: {', '.join(parts)}. Total: Rs.{_fmt_num(total)}."
            if is_ur else
            f"Added: {', '.join(parts)}. Running total: Rs.{_fmt_num(total)}."
        )
        amb = data.get("ambiguous", [])
        if amb:
            base += "\n\n" + _ambiguous_reply(amb, language)
        return base

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
            else:
                lines.append(
                    f"Rs.{amount} mein ek {o['unit']} bhi nahi milta — ek {o['unit']} Rs.{price} hai."
                    if is_ur else
                    f"Rs.{amount} isn't enough for one {o['unit']} — one {o['unit']} costs Rs.{price}."
                )
        if any_actionable:
            tail = " Confirm karein?" if is_ur else " Confirm?"
            return " ".join(lines) + tail
        return " ".join(lines)

    if intent == "inventory_query":
        items = data.get("all_items", [])
        if not items:
            return "Stock khali hai." if is_ur else "Shop is empty."
        lines = [
            f"- {it['name']}: Rs.{_fmt_num(it['unit_price'])}/{it['unit']} "
            f"({_fmt_num(it['stock'])} available)"
            for it in items[:25]
        ]
        header = "Yeh items available hain:" if is_ur else "Items available:"
        return header + "\n" + "\n".join(lines)

    if intent == "confirm":
        return ("Confirm karne ke liye neeche Confirm Order dabaiye."
                if is_ur else "Click Confirm Order below.")

    return None


# ---------------------------------------------------------------
# Responder — only used when we truly need an LLM
# ---------------------------------------------------------------
RESPONDER_PROMPT = """You are DukaanAI — a friendly kiryana shop assistant in Pakistan.
CURRENCY: always "Rs." (never ₹ or $).
LANGUAGE: reply in the customer's language.
RULES: Warm, brief (1-4 sentences). Use ONLY facts in data. No emojis unless customer used one.

DATA:
{data}

Reply as plain text:"""


def generate_reply(customer_message: str, intent: str, data: dict, language: str) -> str:
    # 1. Deterministic replies first — zero tokens
    det = _deterministic_reply(intent, data, language)
    if det:
        return det

    # 2. Try Groq for the rest
    try:
        prompt = RESPONDER_PROMPT.replace("{data}", json.dumps(data, ensure_ascii=False))
        text = _call_groq(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": customer_message},
            ],
            max_tokens=250,
            temperature=0.4,
        )
        return text.strip().replace("₹", "Rs.").replace("$", "Rs.")
    except GroqUnavailable as e:
        # 3. Real rate-limit path — bubble up so UI can render it honestly
        is_ur = language in ("ur_roman", "ur")
        if e.kind == "rate_limit":
            wait_txt = ""
            if e.retry_seconds:
                mins = max(1, e.retry_seconds // 60)
                wait_txt = f" ({mins} min baad try karein)" if is_ur else f" (try again in ~{mins} min)"
            return (
                f"⚠️ AI service ka daily limit khatam ho gaya hai{wait_txt}.\n\n"
                f"Filhal aap mujhe **simple orders** likh kar dein jaise:\n"
                f"- `2kg atta`\n- `1 dozen eggs`\n- `100 ka tel`\n\n"
                f"Yeh offline handle ho jaayenge. 🙂"
                if is_ur else
                f"⚠️ The AI service has reached its daily limit{wait_txt}.\n\n"
                f"For now, please use simple orders like:\n"
                f"- `2kg atta`\n- `1 dozen eggs`\n- `100 ka tel`\n\n"
                f"These are handled locally without the AI service."
            )
        return "Service unavailable — please try again shortly." if not is_ur else \
               "Service filhal unavailable hai — thodi der baad try karein."


def parse_order(message: str) -> dict:
    result = classify_message(message)
    return {
        "items": [p for p in result.get("products", []) if p["quantity"] > 0],
        "unknown": result.get("unknown", []),
    }
