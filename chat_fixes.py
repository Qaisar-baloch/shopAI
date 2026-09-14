"""Deterministic customer-chat fixes layered on top of the existing parser.

These rules run before the general parser so common kiryana phrasing is
resolved from the real SQLite catalog instead of being guessed by the LLM.
"""
import re

from agents import _family_matches, _normalize_unit, _sku_size
from db import list_products

_SIZE_RE = r"kg|kgs|kilo|kilos|kilogram|kilograms|gram|grams|g|litre|liter|litres|liters|ltr|l|ml|dozen|dozz?en|dozzen|piece|pieces|pcs|pc|pack|packet|packs|bag|bags|bottle|bottles"
_PRICE_WORDS = ("price", "rate", "kitne ka", "kitna ka", "kia price", "kya price", "ka price", "ka rate", "kya rate", "how much")
_QUERY_WORDS = {"price", "rate", "kitne", "kitna", "ka", "ke", "ki", "kia", "kya", "hai", "hain", "what", "how", "much", "please", "batao", "bata", "chahiye"}


def _language(message):
    ur = {"hai", "kya", "kia", "ka", "ke", "ki", "aur", "chahiye", "batao", "bata", "hain", "mujhe", "wala", "wali", "karo", "kardo"}
    return "ur_roman" if any(w in ur for w in re.findall(r"[a-z]+", message.lower())) else "en"


def _base_product_name(name):
    """Strip a trailing SKU size/unit so variants share one product family."""
    return re.sub(
        r"\s*\d+(?:\.\d+)?\s*(?:kg|kgs|kilo|kilos|kilogram|kilograms|g|gram|grams|litre|liter|litres|liters|ltr|l|ml|pcs|pc|piece|pieces|dozen|pack|packet|packs|bag|bags|bottle|bottles)\b.*$",
        "",
        name.lower(),
    ).strip()


def _family_catalog_matches(fragment):
    """Return every real SKU belonging to the requested product family."""
    q = re.sub(r"\s+", " ", fragment.strip().lower())
    if not q:
        return []
    products = list_products()
    exact_family = []
    partial = []
    for p in products:
        name = p["name"].lower()
        aliases = [a.strip().lower() for a in (p.get("aliases") or "").split(",") if a.strip()]
        family = _base_product_name(name)
        if q == family or q in aliases:
            exact_family.append(p)
        elif q in name or any(q in a for a in aliases):
            partial.append(p)
    # If the exact alias exists on only one SKU (e.g. "atta" on Atta 5kg),
    # still return the other SKUs whose names belong to the same family.
    if exact_family:
        family_key = _base_product_name(exact_family[0]["name"])
        family_words = set(family_key.split())
        related = [
            p for p in products
            if _base_product_name(p["name"]) == family_key
            or q in _base_product_name(p["name"])
            or any(q in a for a in (p.get("aliases") or "").lower().split(","))
        ]
        # Keep the exact-family rows first, then related variants.
        seen = set()
        result = []
        for p in exact_family + related + partial:
            if p["id"] not in seen:
                seen.add(p["id"])
                result.append(p)
        return result
    return partial


def _catalog_matches(message):
    """Return real catalog rows whose complete name/alias is explicitly present."""
    msg = message.lower()
    found = []
    products = list_products()
    candidates = []
    for p in products:
        candidates.append((p["name"].lower(), p))
        for alias in (p.get("aliases") or "").split(","):
            alias = alias.strip().lower()
            if alias:
                candidates.append((alias, p))
    for phrase, p in sorted(candidates, key=lambda x: len(x[0]), reverse=True):
        if re.search(r"(?<![a-z])" + re.escape(phrase) + r"(?![a-z])", msg):
            if p["id"] not in {x["id"] for x in found}:
                found.append(p)
    return found


def _query_items(message):
    """Resolve the product family/SKU(s) mentioned in a price or availability question."""
    # A bare family question such as "atta hai?" or "sugar ka price?"
    # must show every size/variant, not just the SKU that owns the alias.
    if not re.search(r"\d", message):
        for word in re.findall(r"[a-z]+", message.lower()):
            if word in _QUERY_WORDS:
                continue
            family = _family_catalog_matches(word)
            if family:
                return family

    matches = _catalog_matches(message)
    if matches:
        return matches

    for word in re.findall(r"[a-z]+", message.lower()):
        if word in _QUERY_WORDS:
            continue
        found = _family_catalog_matches(word) or _family_matches(word)
        if found:
            return found
    return []


def _resolve_catalog_size(fragment, qty, user_unit):
    """Resolve a product-first size phrase against all variants in the catalog."""
    candidates = _family_catalog_matches(fragment)
    if not candidates:
        return None
    qty = float(qty)
    unit = _normalize_unit(user_unit)

    # Prefer a family whose base name is exactly what the customer typed.
    exact_family = [p for p in candidates if _base_product_name(p["name"]) == fragment.strip().lower()]
    ordered = exact_family + [p for p in candidates if p not in exact_family]

    for p in ordered:
        size, sku_unit = _sku_size(p["name"])
        if size is not None and sku_unit == unit and abs(size - qty) < 0.05:
            return {"status": "ok", "product": p, "quantity": 1.0}

    # Last resort: exact numeric size even when the displayed selling unit differs.
    for p in ordered:
        size, sku_unit = _sku_size(p["name"])
        if size is not None and abs(size - qty) < 0.05:
            return {"status": "ok", "product": p, "quantity": 1.0}
    return None


def _reverse_size_order(message):
    """Parse customer phrasing such as 'sugar 5kg' / 'atta 10kg'."""
    msg = re.sub(r"\bdozz+en\b", "dozen", message.lower())
    msg = re.sub(r"\bdoz+en\b", "dozen", msg)
    pattern = re.compile(
        rf"(?P<product>[a-z][a-z&' -]*?)\s+(?P<qty>\d+(?:\.\d+)?)\s*(?P<unit>{_SIZE_RE})\b",
        re.I,
    )
    products = []
    seen = set()
    for m in pattern.finditer(msg):
        phrase = m.group("product").strip(" ,.-")
        phrase = re.split(r"\b(?:and|aur)\b", phrase)[-1].strip()
        phrase = re.sub(r"^(?:mujhe|please|give|need|want|chahiye|yeh|ye|wo|woh)\s+", "", phrase).strip()
        if not phrase:
            continue
        qty = float(m.group("qty"))
        unit = m.group("unit")
        result = _resolve_catalog_size(phrase, qty, unit)
        if not result:
            continue
        p = result["product"]
        if p["id"] in seen:
            continue
        seen.add(p["id"])
        products.append({
            "product": p["name"], "product_id": p["id"], "quantity": float(result["quantity"]),
            "unit": p["unit"], "unit_price": float(p["unit_price"]),
            "stock_available": float(p["current_stock"]), "exceeds_stock": float(result["quantity"]) > float(p["current_stock"]),
        })
    return products


def smart_classify_message(message, base_classifier):
    """Return the existing classifier result, with deterministic chat fixes first."""
    msg = message.strip()
    lower = msg.lower()
    language = _language(msg)

    # Price/rate questions must never become orders.
    if any(term in lower for term in _PRICE_WORDS):
        items = _query_items(msg)
        return {
            "intent": "product_query", "language": language, "products": [], "ambiguous": [],
            "spend_orders": [], "unit_mismatch": [], "unknown": [], "query_items": items, "_source": "chat_fix",
        }

    # A bare product or 'product hai' is a question/selection, not a quantity-1 order.
    stripped = re.sub(r"\b(?:hai|hain|available|milta|milti|milega|chahiye)\b", " ", lower)
    if not re.search(r"\d", stripped):
        matches = _query_items(msg)
        if matches:
            return {
                "intent": "product_query", "language": language, "products": [], "ambiguous": [],
                "spend_orders": [], "unit_mismatch": [], "unknown": [], "query_items": matches, "_source": "chat_fix",
            }

    # Customers often say the product first and the SKU size second: 'sugar 5kg'.
    reverse_products = _reverse_size_order(msg)
    if reverse_products:
        return {
            "intent": "order_intent", "language": language, "products": reverse_products, "ambiguous": [],
            "spend_orders": [], "unit_mismatch": [], "unknown": [], "_source": "chat_fix",
        }

    return base_classifier(message)
