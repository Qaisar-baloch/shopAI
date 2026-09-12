# 🛒 DukaanAI — Autonomous AI Business Agent for Micro-Businesses

> **From Customer Message to Business Action.**

DukaanAI lets small shop owners run their business by simply **talking** to an AI assistant — no screens to learn, no spreadsheets to maintain, no training required. Customers send natural-language orders in English, Urdu, or Roman Urdu; the AI parses them, checks real stock, computes real prices from a database, and executes the order end-to-end.

---

## 🎯 Problem

Micro-businesses (kiryana stores, medical stores, small retailers) still manage orders, stock, and customers manually through WhatsApp, notebooks, and spreadsheets. Traditional POS/ERP systems require structured data entry and technical know-how — too complex and too expensive for very small shops.

**Core problem:** Micro-businesses need digital automation, but existing tools demand structured input that owners don't have time to learn.

## 💡 Solution

A multi-agent Streamlit application powered by Groq LLMs where the shop owner simply *talks* to their business software:

- **Order Understanding Agent** — natural language → structured order items
- **Inventory Agent** — real-time stock checks against a SQLite database
- **Alternative Recommendation Agent** — suggests in-stock substitutes when items are unavailable
- **Pricing Engine** — computes authoritative totals from the DB (never from the LLM)
- **Order Execution Agent** — persists orders + deducts stock atomically
- **Low Stock + Restock Agent** — proactively tells the owner what to reorder and how much
- **Shopkeeper Dashboard** — sales KPIs, best-sellers, sales-by-day, and restock recommendations

**🔐 Golden Rule:** The LLM only interprets language. Every product name, price, and stock level comes from SQLite. This eliminates hallucination risk on the facts that matter.

---

## 🏗️ Architecture
