# ShopAI — AI-Assisted Business Assistant for Small Shops

ShopAI is a Streamlit prototype exploring how small retailers can manage customer orders, inventory and sales information through a conversational interface. Customers can describe orders in **English, Urdu or Roman Urdu**. The application combines language understanding with database-backed product, price and stock information.

> **Project status:** portfolio / prototype application. It demonstrates an order and inventory workflow; it is not a production point-of-sale platform and does not process real payments.

## Project links

- **Source:** https://github.com/Qaisar-baloch/shopAI
- **Supporting project documentation:** [Google Drive folder](https://drive.google.com/drive/folders/1bRZrGuRcDmBrluRyZ-CrRk2ZG6o4G-Ou?usp=drive_link)

The application is currently documented through its source repository. A public live demo is not listed here.

## What it does

The Streamlit interface is split into five work areas:

| Page | Purpose |
|---|---|
| Customer Chat | Enter natural-language orders and review parsed items, availability, alternatives and totals |
| Dashboard | View order and sales summaries, best sellers and restock recommendations |
| Inventory | Maintain products, aliases, unit prices and stock levels |
| Orders | Review incoming orders and accept or reject them |
| Customers | View the customer directory and order history |

### Order and inventory flow

1. A customer enters an order in natural language.
2. The local parser handles known product names, aliases, quantities and units. The Groq-backed language workflow is used where AI interpretation is needed.
3. The application resolves product records from SQLite and checks available stock.
4. Product prices and stock values come from the database, not from model-generated text.
5. Out-of-stock items can be accompanied by in-stock alternatives.
6. An accepted customer order is saved with a pending status.
7. The shopkeeper can accept or reject the order. Stock deduction occurs when the order is accepted, rather than at the initial order request.
8. The dashboard and restock module use stored order and inventory data to provide summaries.

## Architecture

~~~text
Customer message
      |
      v
Order parsing / language understanding
(local parser + Groq when required)
      |
      v
SQLite product lookup
      |
      +----> Stock availability
      |
      +----> Database-backed pricing
      |
      +----> Alternative suggestions
      |
      v
Order summary and customer confirmation
      |
      v
Pending order in SQLite
      |
      v
Shopkeeper decision
   /          \
Accept       Reject
  |             |
Deduct stock    Keep stock unchanged
  |
Confirmed order
  |
  v
Dashboard and restock recommendations
~~~

**Data integrity principle:** the language model helps interpret a customer's message. Product identity, price and stock are resolved through application logic and the SQLite database.

## Technology stack

| Layer | Technology |
|---|---|
| Application UI | Streamlit multi-page application |
| Language understanding | Groq API (openai/gpt-oss-120b) and local parsing logic |
| Data storage | SQLite |
| Data processing / dashboard support | Pandas |
| Language | Python |
| Testing | Python test scripts in tests/ |

## Repository structure

~~~text
shopAI/
├── app.py                         # Entry page and database initialization
├── agents.py                      # Groq client, order parsing and language workflow
├── db.py                          # SQLite schema and data-access functions
├── inventory.py                   # Stock checks, pricing, alternatives and order lifecycle
├── restock_agent.py               # Low-stock and reorder recommendations
├── seed.py                        # Sample product data
├── styles.py                      # Shared theme and reusable UI helpers
├── pages/
│   ├── 1_💬_Customer_Chat.py
│   ├── 2_📊_Dashboard.py
│   ├── 3_📦_Inventory.py
│   ├── 4_🧾_Orders.py
│   └── 5_👥_Customers.py
├── tests/
│   ├── test_phase2.py
│   └── test_phase3.py
├── .streamlit/
│   └── secrets.toml.example       # Example secret configuration
├── requirements.txt
└── README.md
~~~

The local SQLite database filename retains a legacy dukaanai.db name for compatibility with the existing code. The current project name and interface branding are **ShopAI**.

## Run locally

### 1. Clone the repository

~~~bash
git clone https://github.com/Qaisar-baloch/shopAI.git
cd shopAI
~~~

### 2. Create and activate a virtual environment

**Windows**

~~~powershell
python -m venv .venv
.venv\Scripts\activate
~~~

**macOS / Linux**

~~~bash
python3 -m venv .venv
source .venv/bin/activate
~~~

### 3. Install dependencies

~~~bash
pip install -r requirements.txt
~~~

### 4. Configure the Groq API key

Copy the example file:

**Windows**

~~~powershell
copy .streamlit\secrets.toml.example .streamlit\secrets.toml
~~~

**macOS / Linux**

~~~bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
~~~

Edit .streamlit/secrets.toml and add your own key:

~~~toml
GROQ_API_KEY = "your_groq_api_key"
~~~

Never commit the real secrets file or publish API credentials.

### 5. Start the application

~~~bash
streamlit run app.py
~~~

The local application normally opens at http://localhost:8501. The app initializes the database and loads sample products when the product table is empty.

## Tests

The repository includes focused scripts for order parsing and inventory / pricing scenarios:

~~~bash
python tests/test_phase2.py
python tests/test_phase3.py
~~~

These scripts exercise sample orders, unknown products, stock availability, alternatives and order summaries. They are lightweight scripts, not a full automated integration-test suite.

## Restock recommendation logic

The current restock module evaluates products at or below their minimum stock level. It uses recent sales over a configurable lookback period (14 days by default) to estimate average daily sales and calculate a suggested reorder quantity.

The target-stock rule in the current code is:

~~~text
target_stock = max(min_stock × 3, average_daily_sales × 7)
reorder_qty  = max(1, ceil(target_stock - current_stock))
~~~

An estimated reorder cost and a priority label are also produced. These are heuristic recommendations for the prototype, not a supplier purchasing integration.

## Current scope and limitations

- The project uses a local SQLite database and sample seed data.
- It does not connect to a real payment processor or external POS system.
- Inventory changes and order records are maintained within the application database.
- The AI service requires a valid Groq API key; availability and model access depend on the provider.
- Sample data and prototype logic should be reviewed before adapting the application for a real shop.
- A persistent production database, authentication, authorization, backups, audit logging and transactional concurrency controls would be required before real commercial use.

## Contribution

My work on this project included workflow design, application testing and iterative improvements with AI-assisted development. The repository contains the implementation and supporting scripts for the current prototype.

## License

See LICENSE for the repository license.
