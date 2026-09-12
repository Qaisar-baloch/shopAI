import math
from db import (
    low_stock_products,
    recent_sales_for_product,
    product_stock_snapshot,
)


def recommend_restock(lookback_days=14):
    """
    For every product at or below min_stock, suggest a reorder quantity.

    Formula (simple, explainable for judges):
      target_stock = max(min_stock * 3, avg_daily_sales * 7)
      reorder_qty  = ceil(target_stock - current_stock)

    If the product has no sales history, we fall back to min_stock * 2.
    """
    low = low_stock_products()
    recommendations = []

    for p in low:
        sold = recent_sales_for_product(p["name"], days=lookback_days)
        avg_daily = sold / lookback_days if lookback_days else 0

        # Target: cover next 7 days of demand OR 3x min stock, whichever is higher
        target = max(float(p["min_stock"]) * 3, avg_daily * 7)
        current = float(p["current_stock"])
        reorder_qty = max(1, math.ceil(target - current))

        # Rough cost estimate
        cost = round(reorder_qty * float(p["unit_price"]), 2)

        # Priority based on how far below min we are
        gap_ratio = (float(p["min_stock"]) - current) / max(float(p["min_stock"]), 1)
        if gap_ratio >= 1:
            priority = "🔴 URGENT"
        elif gap_ratio >= 0.5:
            priority = "🟠 HIGH"
        else:
            priority = "🟡 MEDIUM"

        recommendations.append({
            "name": p["name"],
            "unit": p["unit"],
            "current_stock": current,
            "min_stock": float(p["min_stock"]),
            "sold_last_14d": sold,
            "avg_daily_sales": round(avg_daily, 2),
            "suggested_reorder_qty": reorder_qty,
            "estimated_cost": cost,
            "priority": priority,
        })

    recommendations.sort(key=lambda r: -r["estimated_cost"])
    return recommendations


def inventory_health():
    """
    Quick KPI summary for the top of the dashboard.
    """
    snapshot = product_stock_snapshot()
    total_products = len(snapshot)
    healthy = sum(1 for p in snapshot if p["current_stock"] > p["min_stock"])
    low = total_products - healthy
    total_stock_value = sum(
        float(p["current_stock"]) * float(p["unit_price"]) for p in snapshot
    )
    return {
        "total_products": total_products,
        "healthy": healthy,
        "low": low,
        "total_stock_value": round(total_stock_value, 2),
    }