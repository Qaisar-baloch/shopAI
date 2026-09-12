import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents import parse_order

# Make sure the DB is seeded first!
from db import init_db, get_conn
init_db()

# --- Test messages ---
tests = [
    "2kg atta, 1 dozen eggs aur 2 doodh",
    "1 chawal aur 2 bread",
    "mujhe 3 kg cheeni chahiye",
    "give me 1 pizza and 2kg atta",  # pizza doesn't exist
]

for msg in tests:
    print(f"\n{'='*60}")
    print(f"Customer: {msg}")
    result = parse_order(msg)

    if "error" in result:
        print(f"ERROR: {result['error']}")
        continue

    print("Items:")
    for item in result["items"]:
        print(f"  - {item['product']} | {item['quantity']} {item['unit']} "
              f"| Rs.{item['unit_price']} each")

    if result["unknown"]:
        print(f"Unknown (not in catalog): {result['unknown']}")