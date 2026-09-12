import sqlite3
from datetime import datetime

DB_PATH = "dukaanai.db"

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
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
        status TEXT DEFAULT 'CONFIRMED',
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

def list_products():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM products").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def find_product(name_or_alias: str):
    name_or_alias = name_or_alias.strip().lower()
    conn = get_conn()
    rows = conn.execute("SELECT * FROM products").fetchall()
    conn.close()
    for r in rows:
        r = dict(r)
        names = [r["name"].lower()]
        if r["aliases"]:
            names += [a.strip().lower() for a in r["aliases"].split(",")]
        if name_or_alias in names:
            return r
    return None

def get_product_by_id(pid):
    conn = get_conn()
    r = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    conn.close()
    return dict(r) if r else None

def update_stock(pid, new_stock):
    conn = get_conn()
    conn.execute("UPDATE products SET current_stock=? WHERE id=?", (new_stock, pid))
    conn.commit()
    conn.close()

def low_stock_products():
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM products WHERE current_stock <= min_stock"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def create_order(customer, items):
    total = sum(i["quantity"] * i["unit_price"] for i in items)
    conn = get_conn()
    c = conn.cursor()
    code = "ORD-" + datetime.now().strftime("%Y%m%d%H%M%S")
    c.execute(
        "INSERT INTO orders (order_code, customer, total, status, created_at) VALUES (?,?,?,?,?)",
        (code, customer, total, "PENDING", datetime.now().isoformat())
    )
    order_id = c.lastrowid
    for i in items:
        c.execute("""
            INSERT INTO order_items
            (order_id, product_id, product_name, quantity, unit, unit_price, line_total)
            VALUES (?,?,?,?,?,?,?)
        """, (order_id, i["product_id"], i["product_name"], i["quantity"],
              i["unit"], i["unit_price"], i["quantity"] * i["unit_price"]))
    conn.commit()
    conn.close()
    return order_id, code, total

def dashboard_stats():
    conn = get_conn()
    total_orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    total_sales = conn.execute("SELECT COALESCE(SUM(total),0) FROM orders").fetchone()[0]
    best = conn.execute("""
        SELECT product_name, SUM(quantity) as qty
        FROM order_items GROUP BY product_name ORDER BY qty DESC LIMIT 5
    """).fetchall()
    by_day = conn.execute("""
        SELECT substr(created_at,1,10) as day, SUM(total) as sales
        FROM orders GROUP BY day ORDER BY day
    """).fetchall()
    conn.close()
    return {
        "total_orders": total_orders,
        "total_sales": total_sales,
        "best_sellers": [dict(r) for r in best],
        "sales_by_day": [dict(r) for r in by_day],
    }

# ---------------------------------------------------------------
# Phase 5: stock deduction + order fetch helpers
# ---------------------------------------------------------------
def deduct_stock(product_id, quantity):
    """
    Atomically deduct `quantity` from product's current_stock.
    Raises ValueError if it would go negative.
    """
    conn = get_conn()
    c = conn.cursor()
    row = c.execute(
        "SELECT current_stock, name, unit FROM products WHERE id=?",
        (product_id,)
    ).fetchone()

    if not row:
        conn.close()
        raise ValueError(f"Product {product_id} not found")

    current = float(row["current_stock"])
    qty = float(quantity)

    if qty > current:
        conn.close()
        raise ValueError(
            f"Insufficient stock for {row['name']}: "
            f"requested {qty}, only {current} {row['unit']} left"
        )

    new_stock = round(current - qty, 4)
    c.execute("UPDATE products SET current_stock=? WHERE id=?", (new_stock, product_id))
    conn.commit()
    conn.close()
    return new_stock


def get_order_with_items(order_id):
    """Fetch one order plus its line items."""
    conn = get_conn()
    order = conn.execute(
        "SELECT * FROM orders WHERE id=?", (order_id,)
    ).fetchone()
    items = conn.execute(
        "SELECT * FROM order_items WHERE order_id=?", (order_id,)
    ).fetchall()
    conn.close()
    if not order:
        return None
    return {"order": dict(order), "items": [dict(i) for i in items]}


def recent_orders(limit=10):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ---------------------------------------------------------------
# Phase 6: analytics for shopkeeper dashboard
# ---------------------------------------------------------------
def sales_by_product(limit=10):
    """Total quantity + revenue per product."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT
            product_name,
            SUM(quantity)  AS total_qty,
            SUM(line_total) AS total_revenue,
            COUNT(DISTINCT order_id) AS times_ordered
        FROM order_items
        GROUP BY product_name
        ORDER BY total_revenue DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def sales_by_day(limit=14):
    """Daily revenue for the last N days."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT
            substr(created_at, 1, 10) AS day,
            COUNT(*)   AS orders,
            SUM(total) AS revenue
        FROM orders
        GROUP BY day
        ORDER BY day DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]  # chronological for chart


def recent_sales_for_product(product_name, days=14):
    """
    Total sold in last N days for one product.
    Used by the Restock Recommendation Agent.
    """
    conn = get_conn()
    row = conn.execute("""
        SELECT COALESCE(SUM(oi.quantity), 0) AS qty
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        WHERE oi.product_name = ?
          AND o.created_at >= datetime('now', ?)
    """, (product_name, f'-{days} days')).fetchone()
    conn.close()
    return float(row["qty"]) if row else 0.0


def product_stock_snapshot():
    """All products with their current stock + min."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT id, name, unit, current_stock, min_stock, unit_price
        FROM products
        ORDER BY (current_stock - min_stock) ASC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]
    # ---------------------------------------------------------------
# Phase U1: multi-page helpers
# ---------------------------------------------------------------
def add_product(name, aliases, unit, unit_price, current_stock, min_stock):
    conn = get_conn()
    conn.execute("""
        INSERT INTO products (name, aliases, unit, unit_price, current_stock, min_stock)
        VALUES (?,?,?,?,?,?)
    """, (name, aliases, unit, unit_price, current_stock, min_stock))
    conn.commit()
    conn.close()


def update_product(pid, name, aliases, unit, unit_price, current_stock, min_stock):
    conn = get_conn()
    conn.execute("""
        UPDATE products
        SET name=?, aliases=?, unit=?, unit_price=?, current_stock=?, min_stock=?
        WHERE id=?
    """, (name, aliases, unit, unit_price, current_stock, min_stock, pid))
    conn.commit()
    conn.close()


def delete_product(pid):
    conn = get_conn()
    conn.execute("DELETE FROM products WHERE id=?", (pid,))
    conn.commit()
    conn.close()


def all_customers():
    conn = get_conn()
    rows = conn.execute("""
        SELECT customer,
               COUNT(*) AS order_count,
               SUM(total) AS total_spent,
               MAX(created_at) AS last_order
        FROM orders
        WHERE customer IS NOT NULL AND customer != 'Guest'
        GROUP BY customer
        ORDER BY total_spent DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def orders_by_customer(customer):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM orders WHERE customer = ? ORDER BY id DESC", (customer,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_order_status(order_id, status):
    conn = get_conn()
    conn.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))
    conn.commit()
    conn.close()


def pending_orders():
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM orders WHERE status='PENDING' ORDER BY id ASC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def order_items_for(order_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM order_items WHERE order_id=?", (order_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
