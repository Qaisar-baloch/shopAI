from db import list_products, get_product_by_id


# ---------------------------------------------------------------
# Stock check
# ---------------------------------------------------------------
def check_stock(items):
    """
    Takes parsed items from Phase 2 and returns a status for each.
    Adds: available (bool), stock_left (float), requested (float)
    """
    results = []
    for item in items:
        product = get_product_by_id(item["product_id"])
        if not product:
            results.append({
                **item,
                "available": False,
                "stock_left": 0,
                "reason": "Product not found in DB",
            })
            continue

        stock_left = float(product["current_stock"])
        requested = float(item["quantity"])
        available = requested <= stock_left

        results.append({
            **item,
            "available": available,
            "stock_left": stock_left,
            "requested": requested,
            "reason": "" if available else f"Only {stock_left} {product['unit']} left",
        })
    return results


# ---------------------------------------------------------------
# Pricing engine (authoritative — always from DB)
# ---------------------------------------------------------------
def compute_totals(items):
    """
    Adds line_total to each item, computes grand_total.
    Price always from DB, never from LLM.
    """
    enriched = []
    grand_total = 0.0

    for item in items:
        product = get_product_by_id(item["product_id"])
        unit_price = float(product["unit_price"])   # authoritative source
        qty = float(item["quantity"])
        line_total = round(qty * unit_price, 2)
        grand_total += line_total

        enriched.append({
            **item,
            "unit_price": unit_price,
            "line_total": line_total,
        })

    return {"items": enriched, "grand_total": round(grand_total, 2)}


# ---------------------------------------------------------------
# Alternative recommendation (only real, in-stock DB products)
# ---------------------------------------------------------------
def suggest_alternatives(out_of_stock_item, max_suggestions=3):
    """
    Suggest real products from the same category/unit that ARE in stock.
    NEVER invents products. Returns [] if nothing suitable.
    """
    products = list_products()
    target_unit = out_of_stock_item.get("unit", "").lower()
    target_name = out_of_stock_item.get("product", "").lower()

    candidates = []
    for p in products:
        if p["name"].lower() == target_name:
            continue                                # skip same product
        if float(p["current_stock"]) <= 0:
            continue                                # skip out-of-stock
        score = 0
        if p["unit"].lower() == target_unit:
            score += 2                              # same unit = strong match
        if target_name in (p["aliases"] or "").lower():
            score += 1
        if score > 0:
            candidates.append((score, p))

    candidates.sort(key=lambda x: -x[0])
    return [
        {
            "product": p["name"],
            "unit": p["unit"],
            "unit_price": float(p["unit_price"]),
            "stock_left": float(p["current_stock"]),
        }
        for _, p in candidates[:max_suggestions]
    ]


# ---------------------------------------------------------------
# Build the full order summary the customer confirms
# ---------------------------------------------------------------
def build_order_summary(parsed_items):
    """
    End-to-end pipeline: parsed items → stock check → pricing → summary.
    Returns a dict the UI / chatbot can render directly.
    """
    stock_checked = check_stock(parsed_items)
    priced = compute_totals(stock_checked)

    confirmed_items = []
    out_of_stock = []
    alternatives = {}

    for item in priced["items"]:
        if item["available"]:
            confirmed_items.append(item)
        else:
            out_of_stock.append(item)
            alts = suggest_alternatives(item)
            if alts:
                alternatives[item["product"]] = alts

    # Recompute grand total only for available items
    payable_total = round(sum(i["line_total"] for i in confirmed_items), 2)

    return {
        "items": confirmed_items,
        "out_of_stock": out_of_stock,
        "alternatives": alternatives,
        "grand_total": payable_total,
    }

from db import create_order, deduct_stock


def execute_order(summary, customer="Guest"):
    """
    Persist the order and deduct stock.
    - summary: the dict returned by build_order_summary()
    - customer: name string
    Returns dict: {ok, order_id, order_code, total, error?}
    """
    items = summary.get("items", [])
    if not items:
        return {"ok": False, "error": "No items to order"}

    # Prepare items in the shape create_order expects
    db_items = [
        {
            "product_id": it["product_id"],
            "product_name": it["product"],
            "quantity": it["quantity"],
            "unit": it["unit"],
            "unit_price": it["unit_price"],
        }
        for it in items
    ]

    # 1. Insert order + items in one transaction
    order_id, order_code, total = create_order(customer, db_items)

    # 2. Deduct stock for each item
    deduction_errors = []
    for it in db_items:
        try:
            deduct_stock(it["product_id"], it["quantity"])
        except ValueError as e:
            deduction_errors.append(str(e))

    return {
        "ok": True,
        "order_id": order_id,
        "order_code": order_code,
        "total": total,
        "deduction_warnings": deduction_errors,
    }