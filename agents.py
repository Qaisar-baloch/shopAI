import os
import json
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
    """Returns (size_value, base_unit) from name like 'Atta 5kg' → (5.0, 'kg')."""
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
        return "gram"
    if u in ("liter", "litre", "ltr", "l", "liters", "litres"):
        return "litre"
    if u in ("ml", "milliliter", "millilitre"):
        return "ml"
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


def _product_family_matches(fragment):
    """Return all SKUs matching a product family fragment."""
    products = list_products()
    fragment_l = fragment.lower()
    search_term = ALIAS_HINTS.get(fragment_l, fragment_l)

    matches = [p for p in products if search_term in p["name"].lower()]
    if not matches:
        direct = find_product(fragment)
        if direct:
            matches = [direct]
    return matches


def _resolve_request(fragment, qty, user_unit):
    """
    Resolve a single request to a specific SKU.
    Returns dict:
      {status: 'ok', product: {...}, quantity: float}
      {status: 'ambiguous', family: str, requested_qty, requested_unit,
       options: [full product rows]}
      {status: 'not_found'}
    """
    matches = _product_family_matches(fragment)
    if not matches:
        return {"status": "not_found"}

    user_unit_norm = _normalize_unit(user_unit)
    qty = float(qty) if qty else 1.0

    # ---- Case A: user specified a unit ----
    if user_unit_norm:

        # A1: match a SKU whose catalog `unit` equals user's unit
        for p in matches:
            if p["unit"].lower() == user_unit_norm:
                # Indivisible catalog units (piece, dozen, pack, bag, bottle):
                # use user's quantity directly on this SKU
                return {"status": "ok", "product": p, "quantity": qty}

        # A2: user's unit is a divisible size (kg/litre) — check SKU names
        if user_unit_norm in DIVISIBLE_UNITS:
            for p in matches:
                size, base = _extract_sku_size(p["name"])
                if base == user_unit_norm and size is not None:
                    if abs(size - qty) < 0.05:
                        # exact size match → 1 unit
                        return {"status": "ok", "product": p, "quantity": 1.0}

            # No exact size — check if user's unit could map to any SKU's own unit
            # e.g. "3 litres oil" — oil unit is "bottle", no match. But SKU "3L" exists.
            # We tried A2 already. Nothing exact.

        # A3: try matching by size hint in SKU name using raw user qty
        # e.g. "12 eggs" — 12 matches "Eggs 12 pcs"
        for p in matches:
            size, _ = _extract_sku_size(p["name"])
            if size is not None and abs(size - qty) < 0.05:
                return {"status": "ok", "product": p, "quantity": 1.0}

        # Nothing matched → ambiguous
        return {
            "status": "ambiguous",
            "family": _family_label(fragment, matches),
            "requested_qty": qty,
            "requested_unit": user_unit,
            "options": matches,
        }

    # ---- Case B: no unit given ----
    if len(matches) == 1:
        # Single SKU — use it with user's quantity if unit-appropriate
        p = matches[0]
        if p["unit"].lower() in DIVISIBLE_UNITS:
            # e.g., "2 sugar" where sugar is 1kg (unit kg) — treat qty as kg
            return {"status": "ok", "product": p, "quantity": qty}
        return {"status": "ok", "product": p, "quantity": qty}

    # Multiple SKUs, no unit → ambiguous
    return {
        "status": "ambiguous",
        "family": _family_label(fragment, matches),
        "requested_qty": qty,
        "requested_unit": None,
        "options": matches,
    }


def _family_label(fragment, matches):
    """Human-readable family name for the ambiguous message."""
    if not matches:
        return fragment
    # Take first word(s) before any digit
    first = matches[0]["name"]
    cleaned = re.sub(r"\s*\d+.*$", "", first).strip()
    return cleaned or first


# ---------------------------------------------------------------
# Local parser
# ---------------------------------------------------------------
def _local_parse(message: str) -> dict:
    msg = message.lower().strip()
    products = []          # resolved, ready to add
    ambiguous = []         # need clarification
    spend_orders = []
    unknown = []
    seen_families = set()

    # ---------- Spend orders ----------
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

    # ---------- Quantity orders ----------
    FRACTIONS = {"half": 0.5, "aadha": 0.5, "adha": 0.5, "quarter": 0.25, "pao": 0.25}
    qty_pattern = re.compile(
        r"(\d+(?:\.\d+)?|half|aadha|adha|quarter|pao)\s*"
        r"(kg|kgs|kilo|kilos|kilogram|kilograms|"
        r"gram|grams|g|"
        r"litre|liter|litres|liters|ltr|l|"
        r"ml|"
        r"dozen|"
        r"piece|pieces|pcs|pc|"
        r"pack|packet|packs|"
        r"bag|bags|"
        r"bottle|bottles)?\s+"
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
                "product": p["name"],
                "product_id": p["id"],
                "quantity": result["quantity"],
                "unit": p["unit"],
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

    # ---------- Bare product name (no qty) ----------
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
                        "product": p["name"],
                        "product_id": p["id"],
                        "quantity": 1.0,
                        "unit": p["unit"],
                        "unit_price": float(p["unit_price"]),
                        "stock_available": float(p["current_stock"]),
                        "exceeds_stock": False,
                    })
                else:
                    ambiguous.append({
                        "status": "ambiguous",
                        "family": _family_label(w, matches),
                        "requested_qty": 1.0,
                        "requested_unit": None,
                        "options": matches,
                    })
                break

    # ---------- Intent ----------
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

    # ---------- Language ----------
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
# Groq enhancement (only if local parser found nothing)
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
    if (local["products"] or local["spend_orders"] or local["ambiguous"]
            or local["intent"] != "other"):
        return local

    groq_result = _groq_parse(message)
    if groq_result and (groq_result.get("products") or groq_result.get("spend_orders") or groq_result.get("unknown")):
        return {
            "intent": groq_result.get("intent", local["intent"]),
            "language": groq_result.get("language", local["language"]),
            "products": groq_result.get("products", []),
            "ambiguous": [],
            "spend_orders": groq_result.get("spend_orders", []),
            "unit_mismatch": groq_result.get("unit_mismatch", []),
            "unknown": groq_result.get("unknown", []),
            "_source": "groq",
        }
    return local


# ---------------------------------------------------------------
# Reply generation
# ---------------------------------------------------------------
def _fmt_options(options, is_ur):
    """Format ambiguous options as bullet list."""
    lines = []
    for o in options:
        size, base = _extract_sku_size(o["name"])
        price = _fmt_num(o["unit_price"])
        lines.append(
            f"- {o['name']} — Rs.{price} per {o['unit']}"
        )
    return "\n".join(lines)


def _ambiguous_reply(ambiguous_list, language, added_items=None):
    is_ur = language in ("ur_roman", "ur")
    chunks = []

    if added_items:
        parts = [f"{_fmt_num(a['qty'])} {a['unit']} {a['name']}" for a in added_items]
        if is_ur:
            chunks.append(f"Theek hai, add kar diya: {', '.join(parts)}.")
        else:
            chunks.append(f"Added: {', '.join(parts)}.")

    for item in ambiguous_list:
        family = item["family"]
        opts = _fmt_options(item["options"], is_ur)
        req_qty = _fmt_num(item["requested_qty"])
        req_unit = item.get("requested_unit") or ""

        if is_ur:
            if req_unit:
                chunks.append(
                    f"{family} kg/litre mein nahi — ye available hai:\n{opts}\n"
                    f"Aap ne {req_qty} {req_unit} maanga — kaun sa size chahiye?"
                )
            else:
                chunks.append(
                    f"{family} ye sizes mein milta hai:\n{opts}\nKaun sa chahiye?"
                )
        else:
            if req_unit:
                chunks.append(
                    f"{family} isn't sold by {req_unit}. Available options:\n{opts}\n"
                    f"You asked for {req_qty} {req_unit} — which size would you like?"
                )
            else:
                chunks.append(
                    f"{family} is available in these sizes:\n{opts}\nWhich one?"
                )

    return "\n\n".join(chunks)


def generate_reply(customer_message: str, intent: str, data: dict, language: str) -> str:
    # Deterministic for known intents
    deterministic = _deterministic_reply(intent, data, language)
    if deterministic:
        return deterministic

    # Fallback
    return _fallback_reply(intent, data, language)


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
        # Also mention ambiguous items if present
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
                    f"Rs.{amount} mein {_fmt_num(o['computed_quantity'])} {o['unit']} {o['product']} milega (Rs.{price}/{o['unit']})."
                    if is_ur else
                    f"Rs.{amount} = {_fmt_num(o['computed_quantity'])} {o['unit']} of {o['product']} (Rs.{price}/{o['unit']})."
                )
            elif f == "full_units_with_leftover":
                any_actionable = True
                lines.append(
                    f"Rs.{amount} mein {_fmt_num(o['full_units'])} {o['unit']} {o['product']} (Rs.{price} each), Rs.{_fmt_num(o['leftover'])} bachega."
                    if is_ur else
                    f"Rs.{amount} = {_fmt_num(o['full_units'])} {o['unit']} of {o['product']} (Rs.{price} each), Rs.{_fmt_num(o['leftover'])} leftover."
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

    return None


def _fallback_reply(intent, data, language):
    is_ur = language in ("ur_roman", "ur")

    if intent == "greeting":
        return "Walaikum assalam! Kya chahiye?" if is_ur else "Hi! How can I help you?"

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

    if intent == "confirm":
        return "Confirm karne ke liye neeche Confirm Order dabaiye." if is_ur else "Click Confirm Order below."

    return "Dobara bata dein? Jaise: '5kg atta' ya '1 dozen eggs'." if is_ur \
           else "Say that again? Like: '5kg atta' or '1 dozen eggs'."


def parse_order(message: str) -> dict:
    result = classify_message(message)
    return {
        "items": [p for p in result["products"] if p["quantity"] > 0],
        "unknown": result.get("unknown", []),
    }
