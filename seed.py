from db import init_db, get_conn

def seed():
    init_db()
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM products")
    products = [
        ("Atta",  "atta,wheat flour,flour", "kg",    60.0, 25, 10),
        ("Eggs",  "egg,eggs,anda",          "dozen", 150.0, 12, 5),
        ("Milk",  "milk,doodh,dudh",        "litre", 120.0, 20, 8),
        ("Rice",  "rice,chawal",            "kg",    180.0, 15, 5),
        ("Sugar", "sugar,cheeni",           "kg",    140.0, 8,  4),
        ("Oil",   "oil,tel,cooking oil",    "litre", 350.0, 6,  3),
        ("Bread", "bread,double roti",      "piece", 90.0,  10, 4),
        ("Tea",   "tea,chai,patti",         "gram",  500.0, 3,  2),
    ]
    for p in products:
        c.execute("""
            INSERT INTO products (name, aliases, unit, unit_price, current_stock, min_stock)
            VALUES (?,?,?,?,?,?)
        """, p)
    conn.commit()
    conn.close()
    print("Seeded products OK")

if __name__ == "__main__":
    seed()
