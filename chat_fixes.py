"""Deterministic customer-chat fixes layered on top of the existing parser.

These rules run before the general parser so common kiryana phrasing is
resolved from the real SQLite catalog instead of being guessed by the LLM.
"""
import re

from agents import _family_matches, _resolve_request, _normalize_unit, _sku_size
from db import list_products

_SIZE_RE = r"kg|kgs|kilo|kilos|kilogram|kilograms|gram|grams|g|litre|liter|litres|liters|ltr|l|ml|dozen|dozz?en|dozzen|piece|pieces|pcs|pc|pack|packet|packs|bag|bags|bottle|bottles"
_PRICE_WORDS = ("price", "rate", "kitne ka", "kitna ka", "kia price", "kya price", "ka price", "ka rate", "kya rate", "how much")
_QUERY_WORDS = {"price", "rate", "kitne", "kitna", "ka", "ke", "ki", "kia", "kya", "hai", "hain", "what", "how", "much", "please", "batao", "bata", "chahiye"}


def _language(message):
    ur = {"hai", "kya", "kia", "ka", "ke", "ki", "aur", "chahiye", "batao", "bata", "hain", "mujhe", "wala", "wali", "karo", "kardo"}
    return "ur_roman" if any(w in ur for w in re.findall(r"[a-z]+", message.lower())) else "en"


def _catalog_matches(message):
    """Return real catalog rows whose name/alias is explicitly present."""
    msg = message.lower()
    found = []
    products = list_products()
    # Longest catalog phrases first, so "atta 5kg" wins over "atta".
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
    """Resolve the product(s) mentioned in a price/availability question."""
    matches = _catalog_matches(message)
    if matches:
        return matches
    # Fallback to individual meaningful words/aliases.
    for word in re.findall(r"[a-z]+", message.lower()):
        if word in _QUERY_WORDS:
            continue
        found = _family_matches(word)
        if found:
            return found
    return []


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
        # Keep only the product tail since a preceding item may be in the same message.
        phrase = re.split(r"\b(?:and|aur)\b", phrase)[-1].strip()
        # Remove common command words from the front.
        phrase = re.sub(r"^(?:mujhe|please|give|need|want|chahiye|yeh|ye|wo|woh)\s+", "", phrase).strip()
        if not phrase:
            continue
        qty = float(m.group("qty"))
        unit = m.group("unit")
        result = _resolve_request(phrase, qty, unit)
        if result.get("status") != "ok":
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

    # Price/rate questions must never become orders. Resolve the named SKU(s)
    # from the real catalog and let the UI render only those options.
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
