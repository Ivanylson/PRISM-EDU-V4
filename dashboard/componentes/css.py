import streamlit as st


def injetar_css():
    """Injeta CSS customizado para o tema PRISM-EDU."""
    st.markdown("""
    <style>
    /* ===== PRISM-EDU Custom Theme ===== */

    /* Header & Branding */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%);
    }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h1 {
        background: linear-gradient(90deg, #3b82f6, #8b5cf6);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 800;
    }

    /* Metric Cards */
    [data-testid="stMetric"] {
        background: rgba(30, 41, 59, 0.6);
        border: 1px solid rgba(59, 130, 246, 0.2);
        border-radius: 12px;
        padding: 16px 20px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.3);
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    [data-testid="stMetric"]:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 15px -3px rgba(59, 130, 246, 0.25);
        border-color: rgba(59, 130, 246, 0.5);
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.85rem !important;
        color: #94a3b8 !important;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.8rem !important;
        font-weight: 700 !important;
        color: #f1f5f9 !important;
    }
    [data-testid="stMetricDelta"] > div {
        font-size: 0.8rem !important;
    }

    /* Expanders */
    [data-testid="stExpander"] {
        border: 1px solid rgba(59, 130, 246, 0.15);
        border-radius: 10px;
        margin-bottom: 8px;
    }
    [data-testid="stExpander"]:hover {
        border-color: rgba(59, 130, 246, 0.4);
    }

    /* Tabs / Radio Navigation */
    [data-testid="stHorizontalBlock"] [role="radiogroup"] label {
        border-radius: 8px;
        padding: 6px 14px;
        font-size: 0.82rem;
        transition: all 0.15s ease;
    }
    [data-testid="stHorizontalBlock"] [role="radiogroup"] label:hover {
        background: rgba(59, 130, 246, 0.12);
    }

    /* DataFrames */
    [data-testid="stDataFrame"] {
        border-radius: 10px;
        overflow: hidden;
    }

    /* Buttons */
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #3b82f6, #8b5cf6) !important;
        border: none !important;
        border-radius: 10px !important;
        font-weight: 600 !important;
        transition: all 0.2s ease !important;
    }
    .stButton > button[kind="primary"]:hover {
        transform: translateY(-1px) !important;
        box-shadow: 0 6px 20px rgba(59, 130, 246, 0.4) !important;
    }

    /* Dividers */
    hr {
        border-color: rgba(59, 130, 246, 0.15) !important;
    }

    /* Headers */
    h1, h2, h3 {
        color: #f1f5f9 !important;
    }
    h2 {
        border-bottom: 2px solid rgba(59, 130, 246, 0.2);
        padding-bottom: 8px;
    }

    /* Footer branding */
    .prism-footer {
        text-align: center;
        color: #64748b;
        font-size: 0.75rem;
        padding: 20px 0;
        border-top: 1px solid rgba(59, 130, 246, 0.1);
        margin-top: 40px;
    }

    /* Scrollbar */
    ::-webkit-scrollbar { width: 6px; }
    ::-webkit-scrollbar-track { background: #1e293b; }
    ::-webkit-scrollbar-thumb { background: #475569; border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: #64748b; }

    /* Plotly charts container */
    .js-plotly-plot {
        border-radius: 10px;
    }
    </style>
    """, unsafe_allow_html=True)
