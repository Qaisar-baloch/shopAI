from db import (
    list_products,
    get_product_by_id,
    create_order,
    deduct_stock,
)


# ---------------------------------------------------------------
# Stock check
# ---------------------------------------------------------------
def check_stock(items):
    """
    Takes parsed items and returns a status for each.
    Adds: available, stock_left, requested, reason.
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
# Pricing
# ---------------------------------------------------------------
def compute_totals(items):
    enriched = []
    grand_total = 0.0
    for item in items:
        product = get_product_by_id(item["product_id"])
        unit_price = float(product["unit_price"])
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
# Alternatives
# ---------------------------------------------------------------
def suggest_alternatives(out_of_stock_item, max_suggestions=3):
    products = list_products()
    target_unit = out_of_stock_item.get("unit", "").lower()
    target_name = out_of_stock_item.get("product", "").lower()

    candidates = []
    for p in products:
        if p["name"].lower() == target_name:
            continue
        if float(p["current_stock"]) <= 0:
            continue
        score = 0
        if p["unit"].lower() == target_unit:
            score += 2
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
# Summary
# ---------------------------------------------------------------
def build_order_summary(parsed_items):
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

    payable_total = round(sum(i["line_total"] for i in confirmed_items), 2)

    return {
        "items": confirmed_items,
        "out_of_stock": out_of_stock,
        "alternatives": alternatives,
        "grand_total": payable_total,
    }


# ---------------------------------------------------------------
# Order execution (creates PENDING order, no stock deduction yet)
# ---------------------------------------------------------------
def execute_order(summary, customer="Guest"):
    """
    Persist order with status='PENDING'. Stock is deducted later
    when the shopkeeper accepts the order (Phase U2).
    """
    items = summary.get("items", [])
    if not items:
        return {"ok": False, "error": "No items to order"}

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

    order_id, order_code, total = create_order(customer, db_items)

    return {
        "ok": True,
        "order_id": order_id,
        "order_code": order_code,
        "total": total,
        "status": "PENDING",
    }


# ---------------------------------------------------------------
# Accept order (shopkeeper action — deducts stock, sets CONFIRMED)
# ---------------------------------------------------------------
def accept_order(order_id):
    """Deduct stock for all items and mark order CONFIRMED."""
    from db import order_items_for

    items = order_items_for(order_id)
    if not items:
        return {"ok": False, "error": "Order has no items"}

    warnings = []
    for it in items:
        try:
            deduct_stock(it["product_id"], it["quantity"])
        except ValueError as e:
            warnings.append(str(e))

    from db import update_order_status
    update_order_status(order_id, "CONFIRMED")

    return {"ok": True, "warnings": warnings}


def reject_order(order_id, reason="Rejected by shopkeeper"):
    """Mark order REJECTED. No stock changes."""
    from db import update_order_status
    update_order_status(order_id, "REJECTED")
    return {"ok": True, "reason": reason}
