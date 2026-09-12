from db import get_conn


def _init_tables_quiet():
    """Create tables without triggering auto-seed (avoids recursion)."""
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        aliases TEXT,
        unit TEXT NOT NULL,
        unit_price REAL NOT NULL,
        current_stock REAL NOT NULL,
        min_stock REAL NOT NULL
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_code TEXT UNIQUE,
        customer TEXT,
        total REAL,
        status TEXT DEFAULT 'PENDING',
        created_at TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER,
        product_id INTEGER,
        product_name TEXT,
        quantity REAL,
        unit TEXT,
        unit_price REAL,
        line_total REAL,
        FOREIGN KEY(order_id) REFERENCES orders(id)
    )
    """)

    conn.commit()
    conn.close()


def seed():
    """Insert ~60 realistic products for a Pakistani kiryana store."""
    _init_tables_quiet()
    conn = get_conn()
    c = conn.cursor()

    c.execute("DELETE FROM products")

    # (name, aliases, unit, unit_price, current_stock, min_stock)
    products = [
        # ---- FLOUR ----
        ("Atta 5kg",          "atta, aata, flour, wheat flour, 5kg atta",         "bag",    300.0, 30, 8),
        ("Atta 10kg",         "atta 10, 10kg atta, flour 10kg",                   "bag",    550.0, 20, 5),
        ("Fine Atta 5kg",     "fine atta, maida 5, maida",                        "bag",    340.0, 15, 5),
        ("Besan 1kg",         "besan, gram flour, chanay ka atta",                "pack",   220.0, 20, 6),

        # ---- RICE ----
        ("Basmati Rice 2kg",  "chawal, rice, basmati, chawal 2, rice 2kg",        "bag",    280.0, 30, 8),
        ("Basmati Rice 5kg",  "chawal 5, rice 5kg, basmati 5",                    "bag",    650.0, 18, 5),
        ("Sella Rice 5kg",    "sella, sella rice, golden rice",                   "bag",    720.0, 12, 4),
        ("Pulao Rice 1kg",    "pulao rice, yakhni rice",                          "kg",     220.0, 15, 5),

        # ---- DAIRY / MILK ----
        ("Milk 1L",           "milk, doodh, dudh, 1L milk",                       "piece",  200.0, 25, 10),
        ("Milk 1.5L",         "milk 1.5, doodh 1.5, 1.5L milk",                   "piece",  280.0, 15, 8),
        ("Fresh Cream 200ml", "cream, balai, malai",                              "piece",  180.0, 10, 3),
        ("Butter 200g",       "butter, makhan",                                   "piece",  180.0, 20, 6),
        ("Cheese 200g",       "cheese, paneer",                                   "piece",  220.0, 15, 5),
        ("Yogurt 500g",       "yogurt, dahi, curd",                               "pack",   160.0, 18, 6),

        # ---- EGGS ----
        ("Eggs 12 pcs",       "eggs, anda, anday, dozen eggs",                    "dozen",  360.0, 30, 10),
        ("Eggs 6 pcs",        "eggs 6, half dozen eggs",                          "pack",   190.0, 20, 8),
        ("Eggs 30 pcs",       "eggs 30, tray eggs, anda tray",                    "pack",   850.0, 8,  3),

        # ---- BAKERY ----
        ("Bread Large",       "bread, double roti, large bread",                  "piece",  120.0, 25, 10),
        ("Bread Small",       "bread small, choti double roti",                   "piece",  80.0,  30, 12),
        ("Burger Buns 6 pcs", "bun, buns, burger bun",                            "pack",   100.0, 18, 6),
        ("Rusk 400g",         "rusk, toast, cake rusk",                           "pack",   90.0,  22, 8),

        # ---- TEA / SUGAR ----
        ("Tapal Tea 950g",    "tea, chai, patti, tapal 950",                      "pack",   850.0, 12, 4),
        ("Tapal Tea 475g",    "tea 475, chai 475, tapal 475",                     "pack",   450.0, 20, 6),
        ("Vital Tea 475g",    "vital tea, vital chai",                            "pack",   380.0, 15, 5),
        ("Sugar 1kg",         "sugar, cheeni, shakar",                            "kg",     180.0, 40, 15),
        ("Sugar 5kg",         "sugar 5, cheeni 5kg",                              "bag",    850.0, 12, 4),

        # ---- OIL / GHEE ----
        ("Cooking Oil 1L",    "oil, tel, cooking oil, 1L oil",                    "bottle", 350.0, 22, 8),
        ("Cooking Oil 3L",    "oil 3, 3L oil, tel 3 litre",                       "bottle", 950.0, 12, 4),
        ("Dalda 1kg",         "dalda, banaspati, ghee",                           "kg",     1200.0, 10, 3),
        ("Olive Oil 500ml",   "olive oil, zaitoon oil",                           "bottle", 850.0, 8,  3),

        # ---- SPICES ----
        ("Red Chilli 200g",   "chilli, mirch, lal mirch, red chilli",             "pack",   150.0, 25, 8),
        ("Turmeric 200g",     "turmeric, haldi",                                  "pack",   120.0, 25, 8),
        ("Cumin 200g",        "cumin, zeera, jeera",                              "pack",   180.0, 20, 6),
        ("Salt 1kg",          "salt, namak",                                      "pack",   60.0,  40, 15),
        ("Garam Masala 100g", "garam masala, masala",                             "pack",   200.0, 18, 6),

        # ---- CLEANING / PERSONAL CARE ----
        ("Surf Excel 1kg",    "surf, surf excel, detergent 1kg",                  "pack",   420.0, 15, 5),
        ("Surf Excel 500g",   "surf 500, surf excel 500",                         "pack",   220.0, 22, 8),
        ("Ariel 1kg",         "ariel, ariel 1kg",                                 "pack",   450.0, 12, 4),
        ("Lifebuoy Soap",     "lifebuoy, soap, sabun",                            "piece",  85.0,  45, 15),
        ("Lux Soap",          "lux, lux soap",                                    "piece",  95.0,  35, 12),
        ("Safeguard Soap",    "safeguard, safeguard soap",                        "piece",  110.0, 30, 10),
        ("Head & Shoulders 200ml", "shampoo, head shoulders, head and shoulders", "bottle", 280.0, 15, 5),
        ("Pantene 200ml",     "pantene, pantene shampoo",                         "bottle", 320.0, 12, 4),
        ("Colgate 100g",      "colgate, toothpaste, tooth paste",                 "pack",   180.0, 25, 8),

        # ---- DRINKS ----
        ("Nestle Water 1.5L",  "water, pani, nestle water",                       "bottle", 60.0,  50, 20),
        ("Nestle Water 500ml", "water 500, chota pani",                           "bottle", 30.0,  70, 25),
        ("Coca Cola 1.5L",     "coke, cola, coca cola",                           "bottle", 150.0, 30, 10),
        ("Coca Cola 500ml",    "coke 500, cola 500",                              "bottle", 70.0,  45, 15),
        ("Pepsi 1.5L",         "pepsi, pepsi cola",                               "bottle", 150.0, 25, 8),
        ("Sprite 1.5L",        "sprite, sprite drink",                            "bottle", 150.0, 22, 8),
        ("Fanta 1.5L",         "fanta, fanta orange",                             "bottle", 150.0, 20, 6),
        ("Slice 1L",           "slice, slice juice, mango juice",                 "bottle", 220.0, 15, 5),
        ("Nestle Juice 250ml", "juice, nestle juice",                             "pack",   100.0, 30, 10),

        # ---- SNACKS ----
        ("Lays Classic 50g",  "lays, chips, lays classic",                        "pack",   50.0,  40, 15),
        ("Lays Masala 50g",   "lays masala, spicy chips",                         "pack",   50.0,  35, 12),
        ("Kurkure 50g",       "kurkure, kurkure masala",                          "pack",   40.0,  45, 15),
        ("Slanty 50g",        "slanty, slanty chips",                             "pack",   40.0,  40, 12),
        ("Good Day 100g",     "good day, good day biscuit",                       "pack",   45.0,  38, 12),
        ("Oreo 50g",          "oreo, oreo biscuit",                               "pack",   55.0,  35, 10),
        ("Sooper Biscuit",    "sooper, sooper biscuit",                           "pack",   40.0,  40, 12),
        ("Dairy Milk 30g",    "dairy milk, chocolate, cadbury",                   "pack",   90.0,  25, 8),
    ]

    for p in products:
        c.execute("""
            INSERT INTO products (name, aliases, unit, unit_price, current_stock, min_stock)
            VALUES (?,?,?,?,?,?)
        """, p)

    conn.commit()
    conn.close()
    print(f"Seeded {len(products)} products")


if __name__ == "__main__":
    seed()
    print("✅ Seed complete")
