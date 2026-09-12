import os
import json
from groq import Groq
from db import find_product, list_products


# ---------------------------------------------------------------
# Groq Client
# ---------------------------------------------------------------
def get_client():
    """
    Initialize Groq client. Key lookup order:
      1. GROQ_API_KEY environment variable
      2. Streamlit secrets (works inside `streamlit run`)
      3. .streamlit/secrets.toml file (BOM-safe, works for plain `python` scripts)
    """
    api_key = os.environ.get("GROQ_API_KEY")

    # Streamlit secrets (when running inside Streamlit)
    if not api_key:
        try:
            import streamlit as st
            api_key = st.secrets.get("GROQ_API_KEY")
        except Exception:
            pass

    # Direct file read (when running as a plain Python script)
    if not api_key:
        secrets_path = os.path.join(".streamlit", "secrets.toml")
        if os.path.exists(secrets_path):
            try:
                import tomllib  # Python 3.11+
                with open(secrets_path, "rb") as f:
                    text = f.read().decode("utf-8-sig")   # strips BOM safely
                data = tomllib.loads(text)
                api_key = data.get("GROQ_API_KEY")
            except ModuleNotFoundError:
                try:
                    import tomli  # Python < 3.11
                    with open(secrets_path, "rb") as f:
                        text = f.read().decode("utf-8-sig")
                    data = tomli.loads(text)
                    api_key = data.get("GROQ_API_KEY")
                except Exception:
                    pass
            except Exception:
                pass

    if not api_key or not str(api_key).startswith("gsk_"):
        raise ValueError(
            "GROQ_API_KEY not found or invalid.\n"
            "→ Set it in .streamlit/secrets.toml as:\n"
            '     GROQ_API_KEY = "gsk_..."\n'
            "Get a free key at https://console.groq.com/keys"
        )

    return Groq(api_key=api_key)


# ---------------------------------------------------------------
# Product Catalog (only real products from DB — never invented)
# ---------------------------------------------------------------
def get_product_catalog():
    """Compact list of real products to feed into the LLM prompt."""
    products = list_products()
    return [
        {"name": p["name"], "aliases": p["aliases"], "unit": p["unit"]}
        for p in products
    ]


# ---------------------------------------------------------------
# System Prompt for the Order Understanding Agent
# ---------------------------------------------------------------
SYSTEM_PROMPT = """You are an Order Understanding Agent for a small shop assistant called DukaanAI.

Your ONLY job: convert a customer's natural-language message into structured order items.

STRICT RULES:
1. You may ONLY use product names from the CATALOG below. Never invent products.
2. You do NOT know prices or stock. Never mention them.
3. If a product isn't in the catalog, put it in the "unknown" list — do NOT include it in items.
4. Recognize English, Urdu, and Roman Urdu (e.g., "doodh" = milk, "atta" = flour, "anda" = egg).
5. Output MUST be valid JSON only. No markdown, no explanations.

CATALOG:
{catalog}

OUTPUT FORMAT (strict JSON):
{{
  "items": [
    {{"product": "exact catalog name", "quantity": 2, "unit": "kg"}},
    {{"product": "exact catalog name", "quantity": 1, "unit": "dozen"}}
  ],
  "unknown": ["product name that was not found"]
}}

EXAMPLES:
Customer: "2kg atta, 1 dozen eggs aur 2 doodh"
Output: {{"items": [{{"product": "Atta", "quantity": 2, "unit": "kg"}}, {{"product": "Eggs", "quantity": 1, "unit": "dozen"}}, {{"product": "Milk", "quantity": 2, "unit": "litre"}}], "unknown": []}}

Customer: "1 chawal aur 2 bread"
Output: {{"items": [{{"product": "Rice", "quantity": 1, "unit": "kg"}}, {{"product": "Bread", "quantity": 2, "unit": "piece"}}], "unknown": []}}
"""


# ---------------------------------------------------------------
# Main Parsing Function
# ---------------------------------------------------------------
def parse_order(message: str) -> dict:
    """
    Converts a natural-language message into validated structured order data.
    Returns: {"items": [...], "unknown": [...]} or {"error": "...", "items": [], "unknown": []}
    """
    client = get_client()
    catalog = get_product_catalog()

    prompt = SYSTEM_PROMPT.replace("{catalog}", json.dumps(catalog, indent=2))

    try:
        response = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": message},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=1000,
        )

        # Check finish_reason BEFORE parsing
        finish_reason = response.choices[0].finish_reason
        if finish_reason != "stop":
            return {
                "error": f"Incomplete response (finish_reason={finish_reason})",
                "items": [],
                "unknown": [],
            }

        raw = response.choices[0].message.content
        parsed = json.loads(raw)

        # Validate every product against the real DB
        validated_items = []
        unknown = list(parsed.get("unknown", []))

        for item in parsed.get("items", []):
            real = find_product(item.get("product", ""))
            if real:
                validated_items.append({
                    "product": real["name"],
                    "product_id": real["id"],
                    "quantity": float(item.get("quantity", 1)),
                    "unit": real["unit"],              # from DB
                    "unit_price": real["unit_price"],  # from DB
                })
            else:
                unknown.append(item.get("product"))

        return {"items": validated_items, "unknown": unknown}

    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON from LLM: {e}", "items": [], "unknown": []}
    except Exception as e:
        return {"error": str(e), "items": [], "unknown": []}