import streamlit as st
from db import init_db, get_conn

st.set_page_config(
    page_title="DukaanAI",
    page_icon="🛒",
    layout="wide",
    initial_sidebar_state="expanded",
)

init_db()


def _ensure_seeded():
    conn = get_conn()
    count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    conn.close()
    if count == 0:
        from seed import seed
        seed()


_ensure_seeded()

# ---- Sidebar branding ----
st.sidebar.title("🛒 DukaanAI")
st.sidebar.caption("Autonomous AI Business Agent")
st.sidebar.divider()

# ---- Landing content ----
st.title("🛒 DukaanAI")
st.caption("Autonomous AI Business Agent for Micro-Businesses")
st.markdown("### *From Customer Message to Business Action.*")

st.divider()

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

st.divider()
st.caption("Built with Streamlit · Groq · SQLite — MVP for hackathon demonstration")
