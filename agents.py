import os
import json
import re
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
    if not api_key and os.path.exists(".streamlit/secrets.toml"):
        try:
            import tomllib
            with open(".streamlit/secrets.toml", "rb") as f:
                api_key = tomllib.loads(f.read().decode("utf-8-sig")).get("GROQ_API_KEY")
        except Exception:
            pass
    if not api_key or not str(api_key).startswith("gsk_"):
        raise ValueError("GROQ_API_KEY not found or invalid.")
    return Groq(api_key=api_key)


class GroqUnavailable(Exception):
    def __init__(self, message, retry_seconds=None, kind="unavailable"):
        super().__init__(message)
        self.retry_seconds = retry_seconds
        self.kind = kind


def _call_groq(messages, max_tokens=300, temperature=0.2, json_mode=False):
    try:
        client = get_client()
        kwargs = {
            "model": "openai/gpt-oss-120b",
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""
    except RateLimitError as e:
        retry_s = None
        m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", str(e))
        if m:
            retry_s = int((float(m.group(1) or 0) * 60) + float(m.group(2)))
        raise GroqUnavailable("Daily token quota reached for the AI service.", retry_s, "rate_limit") from e
    except Exception as e:
        raise GroqUnavailable(f"AI service temporarily unavailable: {str(e)[:160]}", kind="error") from e


# ------------------------------------------------------------------
# Product/size normalization
# ------------------------------------------------------------------
ALIAS_HINTS = {
    "atta": "atta", "aata": "atta", "flour": "atta", "wheat flour": "atta",
    "chawal": "rice", "rice": "rice", "basmati": "rice",
    "doodh": "milk", "dudh": "milk", "milk": "milk",
    "anday": "eggs", "anday": "eggs", "anda": "eggs", "egg": "eggs", "eggs": "eggs",
    "cheeni": "sugar", "shakar": "sugar", "shakkar": "sugar", "sugar": "sugar",
    "namak": "salt", "salt": "salt", "tel": "oil", "oil": "oil",
    "patti": "tea", "chai": "tea", "tea": "tea", "bread": "bread", "roti": "bread",
    "sabun": "soap", "soap": "soap", "pani": "water", "water": "water",
    "chips": "lays", "lays": "lays", "kurkure": "kurkure", "biscuit": "biscuit", "biscuits": "biscuit",
    "shampoo": "shampoo", "cheese": "cheese", "paneer": "cheese", "butter": "butter", "makhan": "butter",
    "yogurt": "yogurt", "dahi": "yogurt", "cream": "cream", "balai": "cream", "malai": "cream",
    "bun": "bun", "buns": "bun", "rusk": "rusk", "surf": "surf", "ariel": "ariel",
    "lux": "lux", "lifebuoy": "lifebuoy", "safeguard": "safeguard", "pantene": "pantene", "colgate": "colgate",
    "coca": "coca", "coke": "coca", "cola": "coca", "pepsi": "pepsi", "sprite": "sprite", "fanta": "fanta",
    "slice": "slice", "sooper": "sooper", "oreo": "oreo", "olive": "olive", "turmeric": "turmeric",
    "haldi": "turmeric", "cumin": "cumin", "zeera": "cumin", "jeera": "cumin", "garam": "garam",
}

UNIT_MAP = {
    "kg": "kg", "kgs": "kg", "kilo": "kg", "kilos": "kg", "kilogram": "kg", "kilograms": "kg",
    "g": "gram", "gram": "gram", "grams": "gram",
    "l": "litre", "ltr": "litre", "litre": "litre", "litres": "litre", "liter": "litre", "liters": "litre",
    "ml": "ml", "milliliter": "ml", "millilitre": "ml",
    "pc": "piece", "pcs": "piece", "piece": "piece", "pieces": "piece",
    "dozen": "dozen", "dozen": "dozen", "dozz": "dozen", "dozzen": "dozen", "dozz en": "dozen",
    "pack": "pack", "packs": "pack", "packet": "pack", "packets": "pack",
    "bag": "bag", "bags": "bag", "bottle": "bottle", "bottles": "bottle",
}

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "ek": 1, "aik": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4,
    "paanch": 5, "panch": 5, "che": 6, "chay": 6, "saat": 7, "aath": 8, "nau": 9,
}


def _fmt_num(x):
    try:
        f = float(x)
        return str(int(f)) if f.is_integer() else f"{f:g}"
    except (TypeError, ValueError):
        return str(x)


def _normalize_unit(unit):
    if not unit:
        return None
    u = re.sub(r"\s+", " ", unit.lower().strip())
    return UNIT_MAP.get(u, u)


def _sku_size(name):
    m = re.search(r"(\d+(?:\.\d+)?)\s*(kg|kgs|g|gram|grams|litre|liter|ltr|l|ml|pcs|pc|piece|pieces|dozen|pack|packet|bag|bottle)", name.lower())
    if not m:
        return None, None
    n = float(m.group(1))
    raw = m.group(2)
    unit = _normalize_unit(raw)
    if unit == "gram":
        return n / 1000, "kg"
    if unit == "ml":
        return n / 1000, "litre"
    return n, unit


def _family_matches(fragment):
    q = fragment.strip().lower()
    hint = ALIAS_HINTS.get(q, q)
    products = list_products()
    exact = []
    partial = []
    for p in products:
        name = p["name"].lower()
        aliases = [a.strip().lower() for a in (p.get("aliases") or "").split(",") if a.strip()]
        if q == name or q in aliases or hint == name or hint in aliases:
            exact.append(p)
        elif hint in name or any(hint in a for a in aliases):
            partial.append(p)
    return exact or partial


def _family_label(fragment, matches):
    if not matches:
        return fragment
    return re.sub(r"\s*\d+(?:\.\d+)?\s*.*$", "", matches[0]["name"]).strip() or matches[0]["name"]


def _resolve_request(fragment, qty, user_unit):
    matches = _family_matches(fragment)
    if not matches:
        return {"status": "not_found"}
    qty = float(qty) if qty is not None else 1.0
    u = _normalize_unit(user_unit)

    # Most important rule: a size written by the customer wins over the
    # database selling unit. "5kg sugar" means the Sugar 5kg SKU (unit=bag),
    # not five units of Sugar 1kg (unit=kg).
    if u:
        for p in matches:
            size, sku_unit = _sku_size(p["name"])
            if size is not None and sku_unit == u and abs(size - qty) < 0.05:
                return {"status": "ok", "product": p, "quantity": 1.0}

        # Exact selling unit is next (e.g. "2 dozen eggs").
        for p in matches:
            if _normalize_unit(p["unit"]) == u:
                return {"status": "ok", "product": p, "quantity": qty}

        # Last, allow an exact size in the SKU even if its displayed unit differs.
        for p in matches:
            size, sku_unit = _sku_size(p["name"])
            if size is not None and abs(size - qty) < 0.05:
                return {"status": "ok", "product": p, "quantity": 1.0}

        return {"status": "ambiguous", "family": _family_label(fragment, matches),
                "requested_qty": qty, "requested_unit": user_unit, "options": matches}

    if len(matches) == 1:
        return {"status": "ok", "product": matches[0], "quantity": qty}
    return {"status": "ambiguous", "family": _family_label(fragment, matches),
            "requested_qty": qty, "requested_unit": None, "options": matches}


QTY_RE = re.compile(
    r"(?P<qty>\d+(?:\.\d+)?|half|aadha|adha|quarter|pao|one|two|three|four|five|six|seven|eight|nine|ten|ek|aik|do|teen|char|chaar|paanch|panch|che|chay|saat|aath|nau)\s*"
    r"(?P<unit>kg|kgs|kilo|kilos|kilogram|kilograms|gram|grams|g|litre|liter|litres|liters|ltr|l|ml|dozen|dozz?en|dozzen|piece|pieces|pcs|pc|pack|packet|packs|bag|bags|bottle|bottles)?\s+"
    r"(?P<product>[a-z][a-z&' -]*?)(?=\s+(?:and|aur|,|\d+(?:\.\d+)?\s)|$)", re.I)


def _parse_qty(raw):
    x = raw.lower()
    if x in ("half", "aadha", "adha"):
        return 0.5
    if x in ("quarter", "pao"):
        return 0.25
    if x in NUMBER_WORDS:
        return float(NUMBER_WORDS[x])
    return float(x)


def _local_parse(message):
    msg = message.lower().strip()
    products, ambiguous, spend_orders, unknown = [], [], [], []
    seen_ids = set()
    seen_families = set()

    # Normalize common Roman-Urdu spellings without changing product names.
    msg_for_parse = re.sub(r"\bdozz+en\b", "dozen", msg)
    msg_for_parse = re.sub(r"\bdoz+en\b", "dozen", msg_for_parse)

    for m in QTY_RE.finditer(msg_for_parse):
        qty = _parse_qty(m.group("qty"))
        unit = m.group("unit")
        word = m.group("product").strip(" ,.-")
        # Trim conversational tails that can be captured after a product.
        word = re.split(r"\s+(?:kar do|kardo|chahiye|de do|dedo|please|hain|hai)$", word)[0].strip()
        if not word:
            continue
        result = _resolve_request(word, qty, unit)
        if result["status"] == "ok":
            p = result["product"]
            if p["id"] in seen_ids:
                continue
            seen_ids.add(p["id"])
            q = float(result["quantity"])
            stock = float(p["current_stock"])
            products.append({
                "product": p["name"], "product_id": p["id"], "quantity": q,
                "unit": p["unit"], "unit_price": float(p["unit_price"]),
                "stock_available": stock, "exceeds_stock": q > stock,
            })
        elif result["status"] == "ambiguous":
            fam = result["family"].lower()
            if fam not in seen_families:
                seen_families.add(fam)
                ambiguous.append(result)
        else:
            unknown.append(word)

    # Money-based orders such as "100 ka tel" / "Rs 500 oil".
    spend_re = re.compile(r"(\d+)\s*(?:rs\.?|rupay(?:e|a)?|pkr|rupees?|ka|ke|ki|of)\s+([a-z]+)", re.I)
    for m in spend_re.finditer(msg_for_parse):
        amount = float(m.group(1)); word = m.group(2).lower()
        real = (_family_matches(word) or [None])[0]
        if not real:
            continue
        price = float(real["unit_price"])
        full = int(amount // price) if price else 0
        frac = round(amount / price, 3) if price else 0
        divisible = _normalize_unit(real["unit"]) in {"kg", "gram", "litre", "ml"}
        spend_orders.append({
            "product": real["name"], "product_id": real["id"], "amount": amount,
            "unit": real["unit"], "unit_price": price,
            "computed_quantity": frac if divisible else full,
            "fulfilment": "fraction" if divisible else ("full_units_with_leftover" if full else "insufficient"),
            "full_units": full, "leftover": round(amount - full * price, 2),
            "stock_available": float(real["current_stock"]),
            "exceeds_stock": (frac if divisible else full) > float(real["current_stock"]),
        })

    # Bare product is a QUERY, never an automatic quantity-1 order.
    if not products and not spend_orders and not ambiguous:
        stop = {"the","and","for","with","have","want","need","please","give","some","hai","kya","kia","ka","ke","ki","aur","chahiye","dedo","hain","mein","se","par","salam","salaam","assalam","assalamu","asalam","alaikum","allaikum","aliakum","hello","hi","hey","aoaa","bol","rahe","ho","me","my","is","it","what","price","rate"}
        for w in re.findall(r"\b[a-z]{3,}\b", msg_for_parse):
            if w in stop:
                continue
            matches = _family_matches(w)
            if matches:
                ambiguous.append({"status":"ambiguous","family":_family_label(w,matches),"requested_qty":None,"requested_unit":None,"options":matches}) if len(matches)>1 else products.append({
                    "product":matches[0]["name"],"product_id":matches[0]["id"],"quantity":1.0,
                    "unit":matches[0]["unit"],"unit_price":float(matches[0]["unit_price"]),
                    "stock_available":float(matches[0]["current_stock"]),"exceeds_stock":False})
                break

    greeting = any(re.search(rf"\b{re.escape(w)}\b", msg_for_parse) for w in ("salam","salaam","assalam","hello","hi","hey"))
    inventory = any(x in msg_for_parse for x in ("stock", "inventory", "kya kya", "kia kia", "show me", "list all", "menu", "dikhao", "available items", "what do you have"))
    price_words = any(x in msg_for_parse for x in ("price", "rate", "kitne ka", "kia price", "kya price", "how much"))
    if products or spend_orders or ambiguous:
        intent = "order_intent" if (products or spend_orders) else "ambiguous_request"
    elif greeting and len(msg_for_parse.split()) <= 6:
        intent = "greeting"
    elif inventory:
        intent = "inventory_query"
    elif price_words:
        intent = "product_query"
    elif any(x in msg_for_parse.split() for x in ("yes","haan","ok","confirm","theek")):
        intent = "confirm"
    elif any(x in msg_for_parse.split() for x in ("no","nahi","cancel","chhoro")):
        intent = "cancel"
    else:
        intent = "other"

    ur = {"hai","kya","kia","ka","ke","ki","aur","chahiye","dedo","hain","mein","kaisa","salam","salaam","assalam","alaikum","allaikum","bhai","aap","tum","mujhe","do","de","dena","lena","kro","karo","bol","rahe","wala","wali","kar","kardo"}
    language = "ur_roman" if any(w in ur for w in re.findall(r"[a-z]+", msg_for_parse)) else "en"
    return {"intent":intent,"language":language,"products":products,"ambiguous":ambiguous,"spend_orders":spend_orders,"unit_mismatch":[],"unknown":unknown,"_source":"local"}


# ------------------------------------------------------------------
# Conversational size-selection support
# ------------------------------------------------------------------
def resolve_pending_selection(message, ambiguous_list):
    if not ambiguous_list:
        return None
    msg = message.lower().strip()
    # "5kg wala", "5 kg wala kar do", "the 10kg one"
    size_match = re.search(r"(\d+(?:\.\d+)?)\s*(kg|kgs|g|gram|grams|l|litre|liter|ml|pcs|piece|dozen|dozz?en|pack|bag|bottle)\b", msg)
    ordinal = None
    for pattern, idx in ((r"\b(?:pehla|first|1st)\b",0),(r"\b(?:doosra|dusra|second|2nd)\b",1),(r"\b(?:teesra|third|3rd)\b",2)):
        if re.search(pattern,msg): ordinal=idx; break
    target = ambiguous_list[0]
    options = target.get("options", [])
    chosen = None
    if size_match:
        qty = float(size_match.group(1)); unit = _normalize_unit(size_match.group(2))
        for p in options:
            size, sku_unit = _sku_size(p["name"])
            if size is not None and sku_unit == unit and abs(size-qty)<0.05:
                chosen = p; break
            if size is not None and abs(size-qty)<0.05:
                chosen = p; break
    elif ordinal is not None and ordinal < len(options):
        chosen = options[ordinal]
    else:
        # "atta 5kg" / exact SKU name in the follow-up
        for p in options:
            if p["name"].lower() in msg or any(a.strip().lower() in msg for a in (p.get("aliases") or "").split(",")):
                chosen = p; break
    if not chosen:
        return None
    return {
        "product": chosen["name"], "product_id": chosen["id"], "quantity": 1.0,
        "unit": chosen["unit"], "unit_price": float(chosen["unit_price"]),
        "stock_available": float(chosen["current_stock"]),
        "exceeds_stock": float(chosen["current_stock"]) < 1,
    }


SLIM_CLASSIFIER_PROMPT = """Classify this shop-customer message as JSON. Use intent greeting, product_query, inventory_query, order_intent, confirm, cancel, or other. Extract only explicitly requested quantities and product phrases. Never invent products or quantities. Shape: {\"intent\":\"...\",\"language\":\"en\",\"products\":[{\"product\":\"...\",\"quantity\":1}],\"unknown\":[]}."""


def _groq_classify(message):
    raw = _call_groq([
        {"role":"system","content":SLIM_CLASSIFIER_PROMPT},
        {"role":"user","content":message}], max_tokens=220, temperature=0.1, json_mode=True)
    return json.loads(raw)


def classify_message(message):
    local = _local_parse(message)
    # Local parser handles normal orders/questions. Use Groq only for genuinely
    # unstructured text; this keeps the demo fast and protects the token quota.
    if local["intent"] != "other":
        return local
    try:
        result = _groq_classify(message)
        products=[]; unknown=list(result.get("unknown",[]))
        for item in result.get("products",[]):
            real = (_family_matches(str(item.get("product",""))) or [None])[0]
            if real and item.get("quantity") is not None:
                q=float(item["quantity"]); products.append({"product":real["name"],"product_id":real["id"],"quantity":q,"unit":real["unit"],"unit_price":float(real["unit_price"]),"stock_available":float(real["current_stock"]),"exceeds_stock":q>float(real["current_stock"])})
            elif item.get("product"):
                unknown.append(item["product"])
        return {"intent":result.get("intent","other"),"language":result.get("language",local["language"]),"products":products,"ambiguous":[],"spend_orders":[],"unit_mismatch":[],"unknown":unknown,"_source":"groq"}
    except GroqUnavailable as e:
        local["_rate_limit"]={"kind":e.kind,"retry_seconds":e.retry_seconds,"message":str(e)}
        return local
    except Exception:
        return local


# ------------------------------------------------------------------
# Grounded deterministic replies
# ------------------------------------------------------------------
def _fmt_options(options):
    return "\n".join(f"- **{p['name']}** — Rs.{_fmt_num(p['unit_price'])} per {p['unit']}" for p in options)


def _ambiguous_reply(items, language):
    ur = language in ("ur_roman","ur")
    chunks=[]
    for item in items:
        opts=_fmt_options(item["options"])
        chunks.append((f"**{item['family']}** ye sizes mein milta hai:\n{opts}\nKaun sa chahiye?" if ur else f"**{item['family']}** comes in these sizes:\n{opts}\nWhich one would you like?"))
    return "\n\n".join(chunks)


def _deterministic_reply(intent,data,language):
    ur=language in ("ur_roman","ur")
    if intent=="greeting": return "Walaikum assalam! Kya chahiye?" if ur else "Hi! How can I help you?"
    if intent=="ambiguous_request": return _ambiguous_reply(data.get("ambiguous",[]),language)
    if intent=="order_intent" and data.get("added_items"):
        parts=[f"{_fmt_num(x['qty'])} {x['unit']} {x['name']}" for x in data["added_items"]]
        return (f"Theek hai, add kar diya: {', '.join(parts)}. Total: Rs.{_fmt_num(data.get('draft_total',0))}." if ur else f"Added: {', '.join(parts)}. Running total: Rs.{_fmt_num(data.get('draft_total',0))}.")
    if intent=="inventory_query":
        items=data.get("all_items",[])
        if not items:return "Stock khali hai." if ur else "Shop is empty."
        return ("Yeh items available hain:" if ur else "Items available:")+"\n"+"\n".join(f"- {x['name']}: Rs.{_fmt_num(x['unit_price'])}/{x['unit']} ({_fmt_num(x['stock'])} available)" for x in items[:25])
    if intent=="product_query":
        items=data.get("all_items",[])
        return ("Yeh items available hain:" if ur else "Here are the available items:")+"\n"+"\n".join(f"- {x['name']}: Rs.{_fmt_num(x['unit_price'])}/{x['unit']}" for x in items[:25])
    if intent=="confirm": return "Neeche Confirm Order dabaiye." if ur else "Click Confirm Order below."
    return None


def generate_reply(customer_message, intent, data, language):
    det=_deterministic_reply(intent,data,language)
    if det:return det
    try:
        facts=json.dumps(data,ensure_ascii=False)
        raw=_call_groq([
            {"role":"system","content":"You are a friendly Pakistani kiryana shop assistant. Reply in the customer's language, briefly and naturally. Use ONLY the verified DATA below. Never invent products, prices, stock, offers, delivery, or timings.\nDATA:\n"+facts},
            {"role":"user","content":customer_message}], max_tokens=220, temperature=0.3)
        return raw.strip().replace("₹","Rs.").replace("$","Rs.")
    except GroqUnavailable as e:
        ur=language in ("ur_roman","ur")
        if e.kind=="rate_limit": return "⚠️ AI limit reached. Simple orders like `5kg atta` and `1 dozen eggs` still work locally." if not ur else "⚠️ AI limit khatam ho gaya. `5kg atta` aur `1 dozen eggs` jaisay simple orders abhi bhi locally chalenge."
        return "Service filhal unavailable hai — thodi der baad try karein." if ur else "Service temporarily unavailable — please try again shortly."


def parse_order(message):
    result=classify_message(message)
    return {"items":[p for p in result.get("products",[]) if p.get("quantity",0)>0],"unknown":result.get("unknown",[])}
