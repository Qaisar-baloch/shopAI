import streamlit as st
from db import init_db, get_conn
from styles import inject_theme, page_header, sidebar_brand, footer

st.set_page_config(
    page_title="DukaanAI",
    page_icon="🛒",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_theme()
sidebar_brand()

init_db()


def _ensure_seeded():
    conn = get_conn()
    count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    conn.close()
    if count == 0:
        from seed import seed
        seed()


_ensure_seeded()

# ---- Landing content ----
page_header(
    "Your shop, in one clear view",
    "RETAIL INTELLIGENCE",
    "Autonomous AI Business Agent for Micro-Businesses. From customer message to business action.",
)

st.markdown("""
### 👈 Pick a page from the sidebar

| Page | What it does |
|------|--------------|
| **💬 Customer Chat** | Customers place orders in English, Urdu, or Roman Urdu |
| **📊 Dashboard** | KPIs, sales trends, restock recommendations |
| **📦 Inventory** | Add, edit, delete products; manage stock |
| **🧾 Orders** | View, accept, reject incoming orders |
| **👥 Customers** | Directory with per-customer history |
""")

st.info(
    "👆 Start with **💬 Customer Chat** to place a test order, "
    "then open **🧾 Orders** as the shopkeeper to accept it."
)

footer()
