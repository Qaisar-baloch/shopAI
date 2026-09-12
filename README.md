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

```
                    Customer message
                          │
                          ▼
              ┌───────────────────────┐
              │  Order Understanding  │  ← Groq LLM
              │  Agent (parse only)   │     (interprets language)
              └───────────┬───────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │   Inventory Agent     │  ← SQLite: real stock
              └───────────┬───────────┘
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
        Stock available        Out of stock
              │                       │
              │              ┌────────┴────────┐
              │              │  Alternative    │  ← SQLite: real
              │              │  Recommendation │     products only
              │              └────────┬────────┘
              ▼                       ▼
              ┌───────────────────────┐
              │   Pricing Engine      │  ← SQLite: real prices
              └───────────┬───────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │   Customer Confirms   │
              └───────────┬───────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │  Order Execution      │  → orders + order_items
              │  Agent (persist)      │  → deduct stock
              └───────────┬───────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │  Low Stock Agent →    │
              │  Restock Recommendation│
              │  → Shopkeeper         │
              │    Dashboard          │
              └───────────────────────┘
```

---

## 🚀 Quick Start (Local)

```bash
git clone https://github.com/Qaisar-baloch/shopAI.git
cd shopAI
pip install -r requirements.txt
```

**Configure your Groq API key.** Create `.streamlit/secrets.toml` (copy from the provided example):

```bash
# Windows
copy .streamlit\secrets.toml.example .streamlit\secrets.toml

# macOS / Linux
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

Then edit `.streamlit/secrets.toml` and paste your real key:

```toml
GROQ_API_KEY = "gsk_your_real_key_here"
```

Get a free key at [console.groq.com/keys](https://console.groq.com/keys) — sign up takes 30 seconds.

**Seed the database and launch:**

```bash
python seed.py           # loads 8 sample products
streamlit run app.py     # opens http://localhost:8501
```

---

## 🧪 Example Orders (Try These)

Paste any of these into the chat:

| Message | What it tests |
|---------|---------------|
| `2kg atta, 1 dozen eggs aur 2 doodh` | Mixed English + Roman Urdu |
| `mujhe 3 kg cheeni chahiye` | Full Roman Urdu sentence |
| `1 chawal aur 2 bread` | Aliases (`chawal` → Rice) |
| `30 kg atta` | Out-of-stock handling + alternatives |
| `1 pizza aur 2kg atta` | Unknown product rejection (no hallucination) |

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| UI & Deployment | [Streamlit](https://streamlit.io) |
| LLM Inference | [Groq](https://groq.com) — `openai/gpt-oss-120b` |
| Database | SQLite (embedded, zero-config) |
| Analytics | Pandas |
| Language | Python 3.11+ |

---

## 📁 Project Structure

```
shopAI/
├── .streamlit/
│   ├── secrets.toml              # ← your real key (gitignored)
│   └── secrets.toml.example      # ← template for cloning
├── tests/
│   ├── test_phase2.py            # Order Understanding Agent tests
│   └── test_phase3.py            # Inventory + Pricing tests
├── agents.py                     # LLM + Order Understanding Agent
├── app.py                        # Streamlit UI (2 tabs)
├── db.py                         # SQLite layer (products, orders, analytics)
├── inventory.py                  # Stock check, pricing, execution
├── restock_agent.py              # Low-stock + reorder recommendation logic
├── seed.py                       # Sample data loader
├── requirements.txt
└── README.md
```

---

## 🎬 Hackathon Demo Flow

1. **Customer Chat tab** → type `2kg atta, 1 dozen eggs aur 2 doodh`
2. Watch the AI parse, check stock, compute total → click **Place Order**
3. Receive `ORD-YYYYMMDDHHMMSS` + total in the chat
4. Try `3 tea` → triggers low-stock scenario
5. **Shopkeeper Dashboard tab** → see KPIs, restock recommendations, best-sellers

---

## 🌐 Live Demo

Deployed on Streamlit Cloud: *(URL added after deployment)*

---

## 📄 License

MIT — built for hackathon demonstration.
