"""
DukaanAI — Custom theme module (Modern SaaS).

Usage in any page:
    from styles import inject_theme, page_header, sidebar_brand, footer
    inject_theme()
    sidebar_brand()
    page_header("Title", "TAG", "Subtitle")
"""

import streamlit as st


NAVY = "#0F1729"
NAVY_2 = "#1A2540"
BLUE = "#3B82F6"
BLUE_DK = "#2563EB"
GREEN = "#10B981"
AMBER = "#F59E0B"
RED = "#EF4444"
GRAY_BG = "#F8FAFC"
GRAY_CARD = "#FFFFFF"
GRAY_BORDER = "#E2E8F0"
TEXT_DK = "#0F172A"
TEXT_MID = "#475569"
TEXT_LT = "#94A3B8"


def inject_theme():
    st.markdown(f"""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');

        /* Hide the default entry-page nav item (shows as "app") */
        [data-testid="stSidebarNav"] ul li:first-child {{
            display: none;
        }}

        /* Workspace label above nav */
        [data-testid="stSidebarNav"]::before {{
            content: "WORKSPACE";
            display: block;
            font-size: 0.65rem;
            font-weight: 600;
            letter-spacing: 0.14em;
            color: {TEXT_LT};
            padding: 0 12px 8px 12px;
            margin-top: 8px;
        }}

        /* Hide the Deploy button (keep Manage app) */
        [data-testid="stAppDeployButton"] {{
            display: none !important;
        }}

        html, body, [class*="css"] {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            color: {TEXT_DK};
        }}
        h1, h2, h3, h4 {{
            font-family: 'Space Grotesk', 'Inter', sans-serif !important;
            color: {TEXT_DK} !important;
            letter-spacing: -0.02em;
        }}
        h1 {{ font-weight: 700 !important; }}
        h2, h3 {{ font-weight: 600 !important; }}

        .stApp {{
            background-color: {GRAY_BG};
        }}
        .block-container {{
            padding-top: 2rem;
            padding-bottom: 3rem;
            max-width: 1300px;
        }}

        [data-testid="stSidebar"] {{
            background-color: {NAVY} !important;
        }}
        [data-testid="stSidebar"] * {{
            color: {TEXT_LT} !important;
        }}
        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3,
        [data-testid="stSidebar"] strong {{
            color: #FFFFFF !important;
            font-family: 'Space Grotesk', sans-serif !important;
        }}
        [data-testid="stSidebar"] a {{
            border-radius: 8px !important;
            padding: 8px 12px !important;
            transition: all 0.15s ease;
        }}
        [data-testid="stSidebar"] a:hover {{
            background-color: {NAVY_2} !important;
        }}
        [data-testid="stSidebar"] a[aria-current="page"] {{
            background-color: {BLUE}33 !important;
            border-left: 3px solid {BLUE} !important;
        }}

        .dukaanai-brand {{
            padding: 1rem 0.5rem 1.25rem 0.5rem;
            border-bottom: 1px solid #FFFFFF22;
            margin-bottom: 1rem;
        }}
        .dukaanai-brand .title {{
            font-family: 'Space Grotesk', sans-serif;
            font-size: 1.4rem;
            font-weight: 700;
            color: #FFFFFF;
            letter-spacing: -0.02em;
            line-height: 1.1;
        }}
        .dukaanai-brand .tag {{
            font-size: 0.68rem;
            text-transform: uppercase;
            letter-spacing: 0.14em;
            color: {TEXT_LT};
            margin-top: 4px;
            font-weight: 500;
        }}

        .stButton > button {{
            border-radius: 8px !important;
            font-weight: 500 !important;
            border: 1px solid {GRAY_BORDER} !important;
            background: #FFFFFF !important;
            color: {TEXT_DK} !important;
            transition: all 0.15s ease;
        }}
        .stButton > button:hover {{
            border-color: {BLUE} !important;
            color: {BLUE} !important;
        }}
        .stButton > button[kind="primary"] {{
            background: {BLUE} !important;
            border-color: {BLUE} !important;
            color: #FFFFFF !important;
        }}
        .stButton > button[kind="primary"]:hover {{
            background: {BLUE_DK} !important;
            border-color: {BLUE_DK} !important;
        }}

        [data-testid="stMetric"] {{
            background: {GRAY_CARD};
            border: 1px solid {GRAY_BORDER};
            border-radius: 12px;
            padding: 1rem 1.25rem;
            box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
        }}
        [data-testid="stMetricLabel"] {{
            color: {TEXT_MID} !important;
            font-size: 0.8rem !important;
            font-weight: 500 !important;
            text-transform: uppercase;
            letter-spacing: 0.06em;
        }}
        [data-testid="stMetricValue"] {{
            font-family: 'Space Grotesk', sans-serif !important;
            color: {TEXT_DK} !important;
            font-weight: 700 !important;
        }}

        [data-testid="stChatMessage"] {{
            border-radius: 12px;
            padding: 0.75rem 1rem;
            margin-bottom: 0.5rem;
            border: 1px solid {GRAY_BORDER};
        }}
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {{
            background: {BLUE}11;
        }}
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) {{
            background: {GRAY_CARD};
        }}

        [data-testid="stChatInput"] textarea {{
            border-radius: 10px !important;
        }}

        [data-testid="stExpander"] {{
            border: 1px solid {GRAY_BORDER} !important;
            border-radius: 10px !important;
            background: {GRAY_CARD};
        }}
        [data-testid="stExpander"] summary {{
            font-weight: 500;
        }}

        [data-testid="stDataFrame"] {{
            border-radius: 10px;
            border: 1px solid {GRAY_BORDER};
        }}

        .stTabs [data-baseweb="tab-list"] {{
            gap: 4px;
            border-bottom: 1px solid {GRAY_BORDER};
        }}
        .stTabs [data-baseweb="tab"] {{
            border-radius: 8px 8px 0 0;
            padding: 8px 16px;
            font-weight: 500;
            color: {TEXT_MID};
        }}
        .stTabs [aria-selected="true"] {{
            color: {BLUE} !important;
            border-bottom: 2px solid {BLUE} !important;
        }}

        [data-testid="stAlert"] {{
            border-radius: 10px;
            border: 1px solid {GRAY_BORDER};
        }}

        .page-header {{
            margin-bottom: 1.5rem;
        }}
        .page-header .pill {{
            display: inline-block;
            font-size: 0.68rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.12em;
            color: {BLUE};
            background: {BLUE}15;
            padding: 4px 12px;
            border-radius: 999px;
            margin-bottom: 12px;
            border: 1px solid {BLUE}33;
        }}
        .page-header .title {{
            font-family: 'Space Grotesk', sans-serif;
            font-size: 2rem;
            font-weight: 700;
            color: {TEXT_DK};
            letter-spacing: -0.025em;
            line-height: 1.15;
            margin: 0 0 0.5rem 0;
        }}
        .page-header .subtitle {{
            font-size: 1rem;
            color: {TEXT_MID};
            line-height: 1.5;
            max-width: 720px;
            margin: 0;
        }}

        .badge {{
            display: inline-block;
            padding: 2px 10px;
            border-radius: 999px;
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }}
        .badge-pending   {{ background: {AMBER}22; color: #B45309; }}
        .badge-confirmed {{ background: {GREEN}22; color: #047857; }}
        .badge-rejected  {{ background: {RED}22;   color: #B91C1C; }}
        .badge-ok        {{ background: {GREEN}22; color: #047857; }}
        .badge-low       {{ background: {AMBER}22; color: #B45309; }}
        .badge-out       {{ background: {RED}22;   color: #B91C1C; }}

        .dukaanai-footer {{
            margin-top: 3rem;
            padding-top: 1.5rem;
            border-top: 1px solid {GRAY_BORDER};
            text-align: center;
            font-size: 0.8rem;
            color: {TEXT_LT};
        }}
    </style>
    """, unsafe_allow_html=True)


def page_header(title: str, tag: str = "", subtitle: str = ""):
    st.markdown(f"""
    <div class="page-header">
        {f'<div class="pill">{tag}</div>' if tag else ''}
        <div class="title">{title}</div>
        {f'<p class="subtitle">{subtitle}</p>' if subtitle else ''}
    </div>
    """, unsafe_allow_html=True)


def sidebar_brand():
    st.sidebar.markdown("""
    <div class="dukaanai-brand">
        <div class="title">🛒 DukaanAI</div>
        <div class="tag">The shop, in sync</div>
    </div>
    """, unsafe_allow_html=True)


def badge(text: str, kind: str = "ok"):
    return f'<span class="badge badge-{kind}">{text}</span>'


def status_to_badge(status: str) -> str:
    mapping = {
        "PENDING": "pending",
        "CONFIRMED": "confirmed",
        "REJECTED": "rejected",
    }
    return badge(status, mapping.get(status.upper(), "ok"))


def footer():
    st.markdown(
        '<div class="dukaanai-footer">'
        'DukaanAI · Autonomous AI Business Agent · MVP for hackathon demonstration'
        '</div>',
        unsafe_allow_html=True,
    )
