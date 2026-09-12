import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents import parse_order
from inventory import build_order_summary
from db import init_db

init_db()

def show(msg):
    print(f"\n{'='*60}")
    print(f"Customer: {msg}")
    parsed = parse_order(msg)

    if "error" in parsed:
        print(f"Parse error: {parsed['error']}")
        return

    if parsed["unknown"]:
        print(f"[unknown products]: {parsed['unknown']}")

    summary = build_order_summary(parsed["items"])

    print("\n--- AVAILABLE ITEMS ---")
    for it in summary["items"]:
        print(f"  {it['product']:8} {it['quantity']:>4} {it['unit']:6} "
              f"x Rs.{it['unit_price']:<7} = Rs.{it['line_total']}")

    if summary["out_of_stock"]:
        print("\n--- OUT OF STOCK ---")
        for it in summary["out_of_stock"]:
            print(f"  {it['product']}: {it['reason']}")
            alts = summary["alternatives"].get(it["product"], [])
            for alt in alts:
                print(f"     ↳ try {alt['product']} ({alt['stock_left']} {alt['unit']} "
                      f"@ Rs.{alt['unit_price']})")

    print(f"\nTOTAL PAYABLE: Rs.{summary['grand_total']}")

# ---- Tests ----
show("2kg atta, 1 dozen eggs aur 2 doodh")           # normal order
show("30 kg atta")                                    # exceeds stock (25 left)
show("5 tea, 2 oil")                                  # tea has low stock (3)
show("1 pizza aur 2 kg atta")                         # unknown + valid