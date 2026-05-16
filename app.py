import streamlit as st
import snowflake.connector
import pandas as pd
import calendar
import math
from datetime import date, timedelta

try:
    import plotly.express as px
    import plotly.graph_objects as go
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False

st.set_page_config(
    page_title="Vahdam Amazon P&L Dashboard",
    layout="wide",
    page_icon="🍵",
    initial_sidebar_state="expanded",
)

# ── Password gate ─────────────────────────────────────────────────────────────
def _check_password():
    """Gate the entire app behind a shared password from secrets.

    Sets st.session_state.auth_ok=True on success. Re-renders the login form
    on every wrong attempt until the right password is entered.
    """
    try:
        expected = st.secrets["auth"]["password"]
    except Exception:
        return True  # no password configured → app is open (fail open for local dev)

    if st.session_state.get("auth_ok"):
        return True

    # Hide the sidebar on the login page
    st.markdown("""
    <style>
      section[data-testid="stSidebar"] { display: none !important; }
      [data-testid="stAppViewContainer"] > .main { background:#FBF5EA; }
      .login-wrap { max-width: 380px; margin: 8vh auto 0 auto; text-align: center; }
      .login-logo { font-size: 32px; font-weight: 700; color: #004A2B;
                    letter-spacing: 4px; margin-bottom: 4px; }
      .login-sub  { font-size: 12px; color: #AB8743; letter-spacing: 3px;
                    text-transform: uppercase; margin-bottom: 28px; }
      .login-card { background: #ffffff; border: 1px solid #d6ccba;
                    border-top: 3px solid #004A2B; border-radius: 10px;
                    padding: 24px 28px; box-shadow: 0 4px 14px rgba(0,74,43,0.10); }
      .login-card label { font-size: 12px !important; color: #AB8743 !important;
                          font-weight: 700; letter-spacing: 0.5px;
                          text-transform: uppercase; }
    </style>
    """, unsafe_allow_html=True)

    st.markdown(
        '<div class="login-wrap">'
        '<div class="login-logo">VAHDAM</div>'
        '<div class="login-sub">Amazon P&amp;L Dashboard</div>'
        '<div class="login-card">', unsafe_allow_html=True)

    pw = st.text_input("Password", type="password", key="_pw_input",
                       placeholder="Enter password to continue")
    submitted = st.button("🔓 Unlock", use_container_width=True, type="primary")

    if submitted:
        if pw == expected:
            st.session_state.auth_ok = True
            # Clear the typed password from session state for safety
            if "_pw_input" in st.session_state:
                del st.session_state["_pw_input"]
            st.rerun()
        else:
            st.error("❌ Incorrect password.")

    st.markdown('</div><div style="text-align:center;color:#7a6a50;font-size:11px;'
                'margin-top:16px;">Internal dashboard · Vahdam India</div></div>',
                unsafe_allow_html=True)
    st.stop()

_check_password()

# ── CSS ──────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    html, body, [class*="css"] { font-family: 'Proxima Nova', Arial, sans-serif; }

    /* ── KPI cards ── */
    .kpi-card {
        background: #ffffff; border: 1px solid #d6ccba;
        border-top: 3px solid #004A2B; border-radius: 10px;
        padding: 14px 18px 12px 18px; text-align: center;
        box-shadow: 0 2px 8px rgba(0,74,43,0.06);
        transition: transform .15s ease, box-shadow .15s ease, border-color .15s ease;
        min-height: 122px; display: flex; flex-direction: column; justify-content: center;
    }
    .kpi-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 14px rgba(0,74,43,0.12);
        border-top-color: #AB8743;
    }
    .kpi-label  { font-size: 10px; color: #AB8743; text-transform: uppercase;
                  letter-spacing: 1.2px; margin-bottom: 6px; font-weight: 700; }
    .kpi-actual { font-size: 24px; font-weight: 700; color: #004A2B; line-height: 1.1; }
    .kpi-budget { font-size: 11px; color: #7a6a50; margin-top: 4px; }
    .kpi-delta  { font-size: 11px; font-weight: 600; margin-top: 6px; }
    .delta-up   { color: #004A2B; }
    .delta-dn   { color: #8b1a1a; }
    .kpi-badge  { display: inline-block; border-radius: 12px; padding: 2px 10px;
                  font-size: 11px; font-weight: 700; margin-top: 6px;
                  letter-spacing: 0.3px; }
    .badge-green { background: #d6ece1; color: #004A2B; }
    .badge-amber { background: #fef3d6; color: #7a5c00; }
    .badge-red   { background: #fde8e8; color: #8b1a1a; }

    /* ── Compact KPI strip (P&L) ── */
    .pnl-strip {
        background: linear-gradient(180deg, #ffffff 0%, #faf5ea 100%);
        border: 1px solid #d6ccba; border-radius: 10px;
        padding: 10px 16px; text-align: center;
        box-shadow: 0 1px 4px rgba(0,74,43,0.05);
        min-height: 78px; display: flex; flex-direction: column; justify-content: center;
    }
    .pnl-strip-label { font-size: 10px; color: #AB8743; text-transform: uppercase;
                       letter-spacing: 1px; font-weight: 700; margin-bottom: 2px; }
    .pnl-strip-val   { font-size: 18px; font-weight: 700; color: #004A2B; line-height: 1.1; }
    .pnl-strip-sub   { font-size: 10.5px; color: #7a6a50; margin-top: 2px; }

    /* ── Typography ── */
    .page-title { font-size: 28px; font-weight: 700; color: #004A2B;
                  margin-bottom: 2px; letter-spacing: -0.4px; }
    .page-sub   { font-size: 13px; color: #AB8743; margin-bottom: 20px; font-weight: 500; }
    .breadcrumb { font-size: 12px; color: #AB8743; margin-bottom: 6px; letter-spacing:.5px; }

    .section-hdr {
        font-size: 15px; font-weight: 700; color: #004A2B;
        margin: 22px 0 10px 0; border-left: 4px solid #AB8743;
        padding-left: 12px; letter-spacing: 0.3px;
    }

    /* ── Sidebar ── */
    section[data-testid="stSidebar"] { background-color: #004A2B !important; }
    section[data-testid="stSidebar"] * { color: #FBF5EA !important; }
    section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p,
    section[data-testid="stSidebar"] h4 { color: #AB8743 !important; font-weight: 700;
                                          letter-spacing: 0.5px; font-size: 12px;
                                          text-transform: uppercase; }
    section[data-testid="stSidebar"] hr { border-color: #AB8743 !important; opacity: 0.4; }

    /* Sidebar inputs — light cream w/ dark text (visible on dark green bg) */
    section[data-testid="stSidebar"] .stDateInput input,
    section[data-testid="stSidebar"] .stTextInput input,
    section[data-testid="stSidebar"] .stMultiSelect > div > div,
    section[data-testid="stSidebar"] .stSelectbox > div > div {
        background-color: #FBF5EA !important; border-color: #AB8743 !important;
        color: #171717 !important;
    }
    section[data-testid="stSidebar"] .stSelectbox > div > div * ,
    section[data-testid="stSidebar"] .stDateInput input,
    section[data-testid="stSidebar"] .stTextInput input,
    section[data-testid="stSidebar"] .stMultiSelect > div > div * {
        color: #171717 !important;
    }
    section[data-testid="stSidebar"] .stTextInput input::placeholder {
        color: #7a6a50 !important; opacity: 0.85;
    }
    /* Dropdown popups (rendered outside sidebar) */
    div[data-baseweb="popover"] li { color: #171717 !important; }

    /* ── Buttons ── */
    div[data-testid="stButton"] > button {
        border-radius: 8px; background-color: #004A2B; color: #FBF5EA;
        border: none; font-weight: 600; letter-spacing: 0.3px;
        transition: background-color .15s ease, transform .1s ease;
    }
    div[data-testid="stButton"] > button:hover {
        background-color: #AB8743; color: #171717; transform: translateY(-1px);
    }
    div[data-testid="stButton"] > button:active { transform: translateY(0); }

    /* ── Tabs ── */
    div[data-baseweb="tab-list"] {
        gap: 6px; border-bottom: 2px solid #d6ccba; padding-bottom: 2px;
    }
    button[data-baseweb="tab"] {
        font-size: 14px !important; font-weight: 600 !important;
        color: #7a6a50 !important; padding: 8px 14px !important;
        border-radius: 6px 6px 0 0 !important;
    }
    button[data-baseweb="tab"][aria-selected="true"] {
        color: #004A2B !important; background: rgba(0,74,43,0.06) !important;
    }
    div[data-baseweb="tab-highlight"] { background-color: #004A2B !important; height: 3px !important; }

    /* ── Auto-narrative card ── */
    .narrative {
        background: linear-gradient(135deg, #ffffff 0%, #faf5ea 60%, #f4e9d2 100%);
        border: 1px solid #d6ccba; border-left: 4px solid #AB8743;
        border-radius: 10px; padding: 14px 20px; margin: 4px 0 18px 0;
        font-size: 14px; line-height: 1.55; color: #2a2520;
        box-shadow: 0 1px 4px rgba(0,74,43,0.05);
    }
    .narrative b, .narrative strong { color: #004A2B; }
    .narrative .nw { color: #1a7a3e; font-weight: 700; }
    .narrative .nd { color: #8b1a1a; font-weight: 700; }
    .narrative .nl { color: #AB8743; font-weight: 700; }

    /* ── Movers chips ── */
    .movers-row { display: flex; flex-wrap: wrap; gap: 8px; margin: 6px 0 12px 0; }
    .mover-chip {
        display: inline-flex; align-items: center; gap: 6px;
        padding: 6px 12px; border-radius: 18px;
        font-size: 12px; font-weight: 600;
        border: 1px solid; background: #ffffff;
    }
    .mover-up   { color: #1a7a3e; border-color: #b6dcc4; background: #eaf6ee; }
    .mover-down { color: #8b1a1a; border-color: #f0c5c5; background: #fbeaea; }

    /* ── CEO hero KPI ── */
    .hero-card {
        background: linear-gradient(180deg, #ffffff 0%, #faf5ea 100%);
        border: 1px solid #d6ccba; border-top: 4px solid #004A2B;
        border-radius: 12px; padding: 20px 22px;
        box-shadow: 0 2px 10px rgba(0,74,43,0.07);
        transition: transform .15s ease, box-shadow .15s ease;
        min-height: 138px; display: flex; flex-direction: column; justify-content: center;
    }
    .hero-card:hover { transform: translateY(-2px); box-shadow: 0 6px 18px rgba(0,74,43,0.12); }
    .hero-label  { font-size: 11px; color: #AB8743; text-transform: uppercase;
                   letter-spacing: 1.4px; font-weight: 700; margin-bottom: 6px; }
    .hero-value  { font-size: 32px; font-weight: 700; color: #004A2B; line-height: 1.05; }
    .hero-sub    { font-size: 12px; color: #7a6a50; margin-top: 6px; }
    .hero-delta  { font-size: 12px; font-weight: 700; margin-top: 4px; }
    .hero-up     { color: #1a7a3e; }
    .hero-down   { color: #8b1a1a; }

    /* ── Breadcrumbs ── */
    .crumbs { display: flex; flex-wrap: wrap; align-items: center; gap: 4px;
              margin-bottom: 4px; font-size: 12px; color: #AB8743;
              letter-spacing: 0.4px; }
    .crumbs .crumb-sep { color: #d6ccba; padding: 0 2px; }
    section[data-testid="stMain"] div[data-testid="stButton"] > button[kind="tertiary"],
    section[data-testid="stMain"] div[data-testid="stButton"] > button.crumb-btn {
        background: transparent !important; color: #AB8743 !important;
        border: none !important; padding: 0 !important;
        font-size: 12px !important; font-weight: 600 !important;
        letter-spacing: 0.4px; text-transform: uppercase;
        min-height: auto !important;
    }
    section[data-testid="stMain"] div[data-testid="stButton"] > button[kind="tertiary"]:hover {
        color: #004A2B !important; text-decoration: underline;
        background: transparent !important; transform: none !important;
    }

    /* ── Forecast card ── */
    .forecast-card {
        background: linear-gradient(180deg, #fff 0%, #f7efde 100%);
        border: 1px solid #d6ccba; border-left: 4px solid #AB8743;
        border-radius: 10px; padding: 14px 18px;
        box-shadow: 0 1px 6px rgba(171,135,67,0.10);
        display: flex; flex-direction: column; gap: 4px;
    }
    .forecast-label { font-size: 10px; color: #AB8743; text-transform: uppercase;
                      letter-spacing: 1.2px; font-weight: 700; }
    .forecast-val   { font-size: 22px; font-weight: 700; color: #004A2B; line-height: 1.1; }
    .forecast-sub   { font-size: 11.5px; color: #7a6a50; }
    .forecast-pace  { font-size: 11px; font-weight: 600; }
    .pace-good { color: #1a7a3e; }
    .pace-warn { color: #AB8743; }
    .pace-bad  { color: #8b1a1a; }

    /* ── Fade-in animation on view change (#11) ── */
    @keyframes fadeSlideIn {
        from { opacity: 0; transform: translateY(8px); }
        to   { opacity: 1; transform: translateY(0); }
    }
    [data-testid="stMainBlockContainer"] > div:first-child {
        animation: fadeSlideIn 0.28s ease-out;
    }
    @media (prefers-reduced-motion: reduce) {
        [data-testid="stMainBlockContainer"] > div:first-child { animation: none; }
        .kpi-card, .hero-card { transition: none !important; }
    }

    /* ── Responsive breakpoints (#15) ── */
    @media (max-width: 900px) {
        .page-title { font-size: 22px; }
        .hero-value { font-size: 24px; }
        .hero-card  { min-height: 110px; padding: 14px 16px; }
        .kpi-card   { min-height: 110px; padding: 12px 14px; }
        .kpi-actual { font-size: 20px; }
        .narrative  { font-size: 13px; padding: 12px 14px; }
        .pnl-strip  { min-height: 68px; padding: 8px 12px; }
        .pnl-strip-val { font-size: 16px; }
        section[data-testid="stSidebar"] { width: 240px !important; }
    }
    @media (max-width: 640px) {
        .page-title { font-size: 19px; }
        .page-sub   { font-size: 12px; }
        .hero-value { font-size: 20px; }
        .hero-card, .kpi-card { padding: 10px 12px; }
        .narrative  { font-size: 12.5px; line-height: 1.45; }
    }

    /* ── Tooltips (#5) — replaces native title= with a styled hover bubble ── */
    [data-tip] { position: relative; cursor: help; }
    [data-tip]:hover::after {
        content: attr(data-tip);
        position: absolute; top: calc(100% + 6px); left: 50%;
        transform: translateX(-50%);
        background: #1a1a1a; color: #FBF5EA;
        padding: 8px 12px; border-radius: 6px;
        font-size: 11.5px; font-weight: 500;
        line-height: 1.4; letter-spacing: 0;
        white-space: pre-wrap; min-width: 200px; max-width: 320px;
        box-shadow: 0 4px 14px rgba(0,0,0,0.18); z-index: 9999;
        text-transform: none; text-align: left;
        pointer-events: none;
    }
    [data-tip]:hover::before {
        content: ""; position: absolute; top: 100%; left: 50%;
        transform: translateX(-50%); margin-top: 1px;
        border: 5px solid transparent; border-bottom-color: #1a1a1a;
        z-index: 9999;
    }

    /* ── Hover row-highlight cursor (#14) ── */
    div[data-testid="stDataFrame"] [data-testid="data-grid-canvas"] {
        cursor: pointer !important;
    }
    div[data-testid="stDataFrame"] [data-testid="StyledFullScreenButton"] {
        cursor: pointer !important;
    }

    /* ── Skeleton loader (#12) ── */
    @keyframes shimmer {
        0%   { background-position: -300px 0; }
        100% { background-position: 300px 0; }
    }
    .skeleton {
        background: linear-gradient(90deg, #ede4d0 0%, #faf5ea 50%, #ede4d0 100%);
        background-size: 600px 100%;
        animation: shimmer 1.4s infinite linear;
        border-radius: 8px;
    }
    .skel-kpi    { height: 122px; }
    .skel-strip  { height: 78px; }
    .skel-hero   { height: 138px; }
    .skel-row    { height: 36px; margin-bottom: 6px; }
    .skel-chart  { height: 240px; }

    /* ── Count-up animation hook (#13) ── */
    .countup { font-variant-numeric: tabular-nums; }

    /* ── Alert banners (#18) ── */
    .alerts-row { display: flex; flex-direction: column; gap: 6px;
                  margin: 8px 0 14px 0; }
    .alert-banner {
        display: flex; align-items: center; gap: 10px;
        padding: 8px 14px; border-radius: 8px;
        font-size: 13px; font-weight: 500;
        border: 1px solid; line-height: 1.3;
    }
    .alert-danger { background: #fbeaea; color: #8b1a1a; border-color: #f0c5c5; }
    .alert-warn   { background: #fef3d6; color: #7a5c00; border-color: #f0dca0; }
    .alert-info   { background: #eaf3fb; color: #0b4a6b; border-color: #c5dcef; }

    /* ── Gauges container ── */
    .gauge-grid { display: grid; gap: 14px; }

    /* ── Print stylesheet (#10) ── */
    @media print {
        section[data-testid="stSidebar"] { display: none !important; }
        section[data-testid="stMain"] { padding: 0 !important; }
        button, div[data-testid="stButton"], .stDownloadButton { display: none !important; }
        div[data-baseweb="tab-list"] { display: none !important; }
        div[data-testid="stToolbar"] { display: none !important; }
        .kpi-card, .hero-card, .pnl-strip, .forecast-card, .narrative {
            page-break-inside: avoid;
            box-shadow: none !important;
            border: 1px solid #888 !important;
        }
        .page-title { font-size: 22px !important; }
        body { background: white !important; }
        section[data-testid="stMain"] > div { background: white !important; }
        div[data-testid="stDataFrame"] { page-break-inside: avoid; }
    }

    /* ── Misc ── */
    hr { border-color: #d6ccba; }
    .small-muted { font-size: 11px; color: #7a6a50; }
</style>
""", unsafe_allow_html=True)

# ── Constants ────────────────────────────────────────────────────────────────
TABLE     = "vahdam_db.maplemonk.vahdam_amazon_pnl_overall_fy27_onwards"
MKTG      = "vahdam_db.maplemonk.VAHDAM_AMAZON_MARKETING"
GEO_ORDER = ["USA", "UK", "DE", "IT", "FR", "ES", "CA", "UAE", "AUS"]
GEO_CASE  = " ".join([f"WHEN '{g}' THEN {i+1}" for i, g in enumerate(GEO_ORDER)])
GEO_EXCL  = "GEO NOT IN ('IN', 'MX')"

# ── Connection ───────────────────────────────────────────────────────────────
@st.cache_resource
def get_conn():
    cfg = st.secrets["snowflake"]
    return snowflake.connector.connect(
        account=cfg["account"], user=cfg["user"], password=cfg["password"],
        warehouse=cfg["warehouse"], role=cfg["role"],
        database=cfg["database"], schema=cfg["schema"],
        client_session_keep_alive=True,
        client_session_keep_alive_heartbeat_frequency=900,  # ping every 15 min
        login_timeout=30,
        network_timeout=60,
    )

# Snowflake error codes that mean "auth token is stale, reconnect and retry"
_SF_RETRY_CODES = {390114, 390112, 390111, 390104, 390195}

@st.cache_data(ttl=300, show_spinner="Loading data…")
def run_query(sql: str) -> pd.DataFrame:
    for attempt in (1, 2):
        try:
            cur = get_conn().cursor()
            cur.execute(sql)
            return cur.fetch_pandas_all()
        except snowflake.connector.errors.ProgrammingError as e:
            code = getattr(e, "errno", None)
            if attempt == 1 and (code in _SF_RETRY_CODES
                                  or "token has expired" in str(e).lower()
                                  or "authenticate again" in str(e).lower()):
                # Drop the cached (stale) connection and try once more
                try:
                    get_conn.clear()
                except Exception:
                    pass
                continue
            raise
        except snowflake.connector.errors.DatabaseError as e:
            if attempt == 1 and ("expired" in str(e).lower()
                                  or "authenticate again" in str(e).lower()):
                try:
                    get_conn.clear()
                except Exception:
                    pass
                continue
            raise

# ── Session state ─────────────────────────────────────────────────────────────
for k, v in [("view","ceo"), ("selected_geo",None), ("selected_subcat",None)]:
    if k not in st.session_state: st.session_state[k] = v

# Hydrate from URL on first load (#19)
if "_url_synced" not in st.session_state:
    try:
        qp = st.query_params
        if "view" in qp and qp["view"] in {"ceo","overview","subcategory","asin","pnl"}:
            st.session_state.view = qp["view"]
        if "geo" in qp:    st.session_state.selected_geo    = qp["geo"]
        if "subcat" in qp: st.session_state.selected_subcat = qp["subcat"]
        if "preset" in qp and "date_preset" not in st.session_state:
            st.session_state.date_preset = qp["preset"]
        if "sku" in qp and "sku_search" not in st.session_state:
            st.session_state.sku_search = qp["sku"]
    except Exception:
        pass
    st.session_state._url_synced = True

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.image("vahdam_logo.webp", use_container_width=True)
    st.markdown("""<div style="text-align:center;color:#AB8743;font-size:11px;
        letter-spacing:2px;text-transform:uppercase;margin-top:-8px;margin-bottom:8px;">
        Amazon P&L Dashboard</div>""", unsafe_allow_html=True)
    st.markdown("---")

    use_inr = st.radio("Currency", ["INR (₹)", "Local Currency"], index=0) == "INR (₹)"
    sfx = "INR" if use_inr else "LOCAL"
    sym = "₹" if use_inr else ""

    # ── Quick Date Presets ──
    st.markdown("#### Quick Presets")
    today  = date.today()
    PRESET_OPTS = ["MTD", "Last 30 Days", "Last 60 Days", "Last 90 Days", "Custom Range"]
    preset = st.selectbox("Date Preset", PRESET_OPTS, index=0, key="date_preset")

    _preset_days = {"Last 30 Days": 30, "Last 60 Days": 60, "Last 90 Days": 90}
    if preset == "MTD":
        d_from, d_to = today.replace(day=1), today
    elif preset in _preset_days:
        d_from, d_to = today - timedelta(days=_preset_days[preset] - 1), today
    else:
        d1, d2 = st.columns(2)
        with d1: d_from = st.date_input("From", value=today.replace(day=1))
        with d2: d_to   = st.date_input("To",   value=today)

    if preset != "Custom Range":
        st.caption(f"📅 {d_from.strftime('%d %b')} – {d_to.strftime('%d %b %Y')}  "
                   f"·  {(d_to - d_from).days + 1} days")

    # ── SKU / ASIN / Product search ──
    st.markdown("---")
    st.markdown("#### Search")
    sku_search = st.text_input("SKU / ASIN / Product",
                               placeholder="e.g. B09YXMVQTV…", key="sku_search")

    # ── Filters ──
    @st.cache_data(ttl=600)
    def get_options():
        return run_query(f"SELECT DISTINCT BRAND,CATEGORY,CHANNEL,GEO,SUB_CATEGORY FROM {TABLE} WHERE {GEO_EXCL}")
    opts = get_options()

    _fc1, _fc2 = st.columns([3, 2])
    with _fc1: st.markdown("#### Filters")
    with _fc2:
        if st.button("⟲ Clear", use_container_width=True, key="clear_filters",
                     help="Clear all filters"):
            for k in ["flt_brand","flt_cat","flt_channel","flt_geo","flt_subcat","sku_search"]:
                if k in st.session_state: st.session_state[k] = [] if k != "sku_search" else ""
            st.rerun()

    f_brand   = st.multiselect("Brand",        sorted(opts["BRAND"].dropna().unique()),
                               key="flt_brand")
    f_cat     = st.multiselect("Category",     sorted(opts["CATEGORY"].dropna().unique()),
                               key="flt_cat")
    _ch_raw   = sorted(opts["CHANNEL"].dropna().unique())
    _ch_disp  = [c.replace("_", " ") for c in _ch_raw]
    _ch_pick  = st.multiselect("Channel", _ch_disp, key="flt_channel")
    f_channel = [c.replace(" ", "_") for c in _ch_pick]
    f_geo     = st.multiselect("GEO",
                               [g for g in GEO_ORDER if g in opts["GEO"].dropna().unique()],
                               key="flt_geo")
    f_subcat  = st.multiselect("Sub-Category", sorted(opts["SUB_CATEGORY"].dropna().unique()),
                               key="flt_subcat")

    # Active-filter count badge
    _active = sum(1 for x in [f_brand, f_cat, f_channel, f_geo, f_subcat] if x)
    if _active:
        st.caption(f"🔵 {_active} filter{'s' if _active != 1 else ''} active")

    # ── Navigation ──
    st.markdown("---")
    if st.button("⭐ CEO Summary", use_container_width=True, key="nav_ceo"):
        st.session_state.view = "ceo"
        st.rerun()
    _nc1, _nc2 = st.columns(2)
    with _nc1:
        if st.button("🏠 Overview", use_container_width=True, key="nav_overview"):
            st.session_state.view = "overview"
            st.rerun()
    with _nc2:
        if st.button("📋 P&L", use_container_width=True, key="nav_pnl"):
            st.session_state.view = "pnl"
            st.rerun()

# ── Month / pro-rata helpers ──────────────────────────────────────────────────
month_start       = d_from.replace(day=1)
_total_days       = calendar.monthrange(d_from.year, d_from.month)[1]
month_end         = date(d_from.year, d_from.month, _total_days)
days_elapsed      = min((d_to - month_start).days + 1, _total_days)

# Previous comparable period (same length, immediately preceding)
_period_len       = (d_to - d_from).days + 1
prev_d_to         = d_from - timedelta(days=1)
prev_d_from       = prev_d_to - timedelta(days=_period_len - 1)

# ── WHERE builder ─────────────────────────────────────────────────────────────
def build_where(geo_override=None, subcat_override=None, date_from=None, date_to=None,
                extra_filters=None, apply_sku=True):
    d1 = date_from or d_from
    d2 = date_to   or d_to
    w  = [f"DAY BETWEEN '{d1}' AND '{d2}'", GEO_EXCL]
    if f_brand:   w.append(f"BRAND IN ({','.join(repr(x) for x in f_brand)})")
    if f_cat:     w.append(f"CATEGORY IN ({','.join(repr(x) for x in f_cat)})")
    if f_channel: w.append(f"CHANNEL IN ({','.join(repr(x) for x in f_channel)})")
    if geo_override:
        w.append(f"GEO = '{geo_override}'")
    elif f_geo:
        w.append(f"GEO IN ({','.join(repr(x) for x in f_geo)})")
    if subcat_override is not None:
        if subcat_override == "(untagged)":
            w.append("COALESCE(NULLIF(SUB_CATEGORY,''),'(untagged)') = '(untagged)'")
        else:
            esc = subcat_override.replace("'", "''")
            w.append(f"UPPER(TRIM(COALESCE(SUB_CATEGORY,''))) = UPPER(TRIM('{esc}'))")
    elif f_subcat:
        w.append(f"SUB_CATEGORY IN ({','.join(repr(x) for x in f_subcat)})")
    # SKU / ASIN / product-name filter applies to all main views unless suppressed
    if apply_sku and sku_search and sku_search.strip():
        t = sku_search.strip().replace("'", "''")
        w.append(f"(UPPER(ASIN) LIKE UPPER('%{t}%') "
                 f"OR UPPER(COALESCE(COMMON_SKU_DESCRIPTION,'')) LIKE UPPER('%{t}%'))")
    if extra_filters:
        w.append(extra_filters)
    return " AND ".join(w)

# ── Formatters ────────────────────────────────────────────────────────────────
def _f(v):
    try:
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return None

def fmt_lakhs(v, signed=False):
    """Auto-scale Indian currency: <1K → raw, <1L → K, <1Cr → L, ≥1Cr → Cr."""
    n = _f(v)
    if n is None: return "—"
    a = abs(n)
    if signed:
        sign = "-" if n < 0 else ("+" if n > 0 else "")
    else:
        sign = "-" if n < 0 else ""
    if a >= 1e7:
        scaled, unit = a / 1e7, "Cr"
    elif a >= 1e5:
        scaled, unit = a / 1e5, "L"
    elif a >= 1e3:
        scaled, unit = a / 1e3, "K"
    else:
        return f"{sign}{sym}{a:,.0f}"
    # 2 decimals when small in its unit, 1 decimal when ≥ 10, 0 when ≥ 100
    if scaled >= 100:
        return f"{sign}{sym}{scaled:,.0f}{unit}"
    if scaled >= 10:
        return f"{sign}{sym}{scaled:,.1f}{unit}"
    return f"{sign}{sym}{scaled:,.2f}{unit}"

def fmt_pct(v):
    v = _f(v); return "—" if v is None else f"{v:.1f}%"

def fmt_num(v, dec=0):
    v = _f(v); return "—" if v is None else f"{v:,.{dec}f}"

def fmt_ccy(v, dec=2):
    v = _f(v); return "—" if v is None else f"{sym}{v:,.{dec}f}"

def prorata_str(actual, fm_budget):
    act, bud = _f(actual), _f(fm_budget)
    if act is None or bud is None or bud == 0: return "—"
    prorata_bud = bud * days_elapsed / _total_days
    if prorata_bud == 0: return "—"
    pct = act / prorata_bud * 100
    arrow = "↑" if pct >= 100 else "↓"
    return f"{arrow} {pct:.1f}%"

def pct_badge(v):
    v = _f(v)
    if v is None: return ""
    cls = "badge-green" if v >= 100 else ("badge-amber" if v >= 80 else "badge-red")
    return f'<span class="kpi-badge {cls}">{v:.1f}%</span>'

def kpi_delta(delta, unit="%", invert=False):
    v = _f(delta)
    if v is None: return ""
    good = (v > 0 and not invert) or (v < 0 and invert)
    cls  = "delta-up" if good else "delta-dn"
    sign = "▲" if v > 0 else "▼"
    return f'<div class="kpi-delta {cls}">{sign} {abs(v):.1f}{unit} vs Bud</div>'

def color_pct(v):
    v = _f(v)
    if v is None: return ""
    if v >= 100: return "background-color:#d6ece1;color:#004A2B;font-weight:600"
    if v >= 80:  return "background-color:#fef3d6;color:#7a5c00;font-weight:600"
    return "background-color:#fde8e8;color:#8b1a1a;font-weight:600"

def color_var(v):
    v = _f(v)
    if v is None: return ""
    return "color:#004A2B;font-weight:600" if v >= 0 else "color:#8b1a1a;font-weight:600"

def color_prorata(s):
    if not isinstance(s, str) or s == "—": return ""
    try:
        pct = float(s[2:].replace("%","").strip())
        if pct >= 100: return "color:#004A2B;font-weight:600"
        if pct >= 80:  return "color:#7a5c00;font-weight:600"
        return "color:#8b1a1a;font-weight:600"
    except Exception:
        return ""

TOTAL_ROW = ";font-weight:700;background:#EDE8DC;color:#004A2B"

# ── SQL helpers ───────────────────────────────────────────────────────────────
def _v1_metrics(sfx):
    return f"""
        SUM(QTY_ACTUAL)                                                                    AS QTY,
        ROUND(SUM(SALES_ACTUAL_{sfx}),0)                                                  AS SALES_ACT,
        ROUND(SUM(SALES_BUDGET_{sfx}),0)                                                  AS SALES_BUD,
        ROUND(SUM(SALES_ACTUAL_{sfx})/NULLIF(SUM(SALES_BUDGET_{sfx}),0)*100,1)            AS REV_PCT,
        ROUND(SUM(CM1_ACTUAL_{sfx})/NULLIF(SUM(SALES_ACTUAL_{sfx}),0)*100,1)             AS CM1_PCT_ACT,
        ROUND(SUM(CM1_BUDGET_{sfx})/NULLIF(SUM(SALES_BUDGET_{sfx}),0)*100,1)             AS CM1_PCT_BUD,
        ROUND(SUM(PM_SPEND_ACTUAL_{sfx})/NULLIF(SUM(SALES_ACTUAL_{sfx}),0)*100,1)        AS ACOS_ACT,
        ROUND(SUM(PM_SPEND_BUDGET_{sfx})/NULLIF(SUM(SALES_BUDGET_{sfx}),0)*100,1)        AS ACOS_BUD,
        ROUND(SUM(CM2_ACTUAL_{sfx})/NULLIF(SUM(SALES_ACTUAL_{sfx}),0)*100,1)             AS CM2_PCT_ACT,
        ROUND(SUM(CM2_BUDGET_{sfx})/NULLIF(SUM(SALES_BUDGET_{sfx}),0)*100,1)             AS CM2_PCT_BUD,
        ROUND(SUM(CM2_ACTUAL_{sfx}),0)                                                    AS CM2_ABS_ACT,
        ROUND(SUM(CM2_BUDGET_{sfx}),0)                                                    AS CM2_ABS_BUD,
        ROUND(SUM(CM2_ACTUAL_{sfx})-SUM(CM2_BUDGET_{sfx}),0)                             AS CM2_VAR,
        ROUND(SUM(CM2_ACTUAL_{sfx})/NULLIF(SUM(CM2_BUDGET_{sfx}),0)*100,1)               AS CM2_ABS_ACHVD_PCT
    """

# ── Queries ───────────────────────────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def get_kpis(where, sfx):
    return run_query(f"""
        SELECT
            ROUND(SUM(SALES_ACTUAL_{sfx}),0)                                              AS SALES_ACT,
            ROUND(SUM(SALES_BUDGET_{sfx}),0)                                              AS SALES_BUD,
            ROUND(SUM(SALES_ACTUAL_{sfx})/NULLIF(SUM(SALES_BUDGET_{sfx}),0)*100,1)       AS REV_PCT,
            ROUND((SUM(SALES_ACTUAL_{sfx})-SUM(SALES_BUDGET_{sfx}))/NULLIF(ABS(SUM(SALES_BUDGET_{sfx})),0)*100,1) AS REV_DELTA,
            ROUND(SUM(CM1_ACTUAL_{sfx})/NULLIF(SUM(SALES_ACTUAL_{sfx}),0)*100,1)         AS CM1_ACT,
            ROUND(SUM(CM1_BUDGET_{sfx})/NULLIF(SUM(SALES_BUDGET_{sfx}),0)*100,1)         AS CM1_BUD,
            ROUND(SUM(CM1_ACTUAL_{sfx})/NULLIF(SUM(SALES_ACTUAL_{sfx}),0)*100
                 -SUM(CM1_BUDGET_{sfx})/NULLIF(SUM(SALES_BUDGET_{sfx}),0)*100,1)         AS CM1_DELTA,
            ROUND(SUM(PM_SPEND_ACTUAL_{sfx})/NULLIF(SUM(SALES_ACTUAL_{sfx}),0)*100,1)    AS ACOS_ACT,
            ROUND(SUM(PM_SPEND_BUDGET_{sfx})/NULLIF(SUM(SALES_BUDGET_{sfx}),0)*100,1)    AS ACOS_BUD,
            ROUND(SUM(PM_SPEND_ACTUAL_{sfx})/NULLIF(SUM(SALES_ACTUAL_{sfx}),0)*100
                 -SUM(PM_SPEND_BUDGET_{sfx})/NULLIF(SUM(SALES_BUDGET_{sfx}),0)*100,1)    AS ACOS_DELTA,
            ROUND(SUM(CM2_ACTUAL_{sfx})/NULLIF(SUM(SALES_ACTUAL_{sfx}),0)*100,1)         AS CM2_ACT,
            ROUND(SUM(CM2_BUDGET_{sfx})/NULLIF(SUM(SALES_BUDGET_{sfx}),0)*100,1)         AS CM2_BUD,
            ROUND(SUM(CM2_ACTUAL_{sfx})/NULLIF(SUM(SALES_ACTUAL_{sfx}),0)*100
                 -SUM(CM2_BUDGET_{sfx})/NULLIF(SUM(SALES_BUDGET_{sfx}),0)*100,1)         AS CM2_DELTA,
            ROUND(SUM(CM2_ACTUAL_{sfx}),0)                                                AS CM2_ABS_ACT,
            ROUND(SUM(CM2_BUDGET_{sfx}),0)                                                AS CM2_ABS_BUD,
            ROUND((SUM(CM2_ACTUAL_{sfx})-SUM(CM2_BUDGET_{sfx}))/NULLIF(ABS(SUM(CM2_BUDGET_{sfx})),0)*100,1) AS CM2_ABS_DELTA
        FROM {TABLE} WHERE {where}
    """)

@st.cache_data(ttl=300, show_spinner=False)
def get_view1(where, sfx):
    m = _v1_metrics(sfx)
    return run_query(f"""
        SELECT GEO, CHANNEL, {m} FROM {TABLE} WHERE {where} GROUP BY GEO, CHANNEL
        UNION ALL
        SELECT GEO, 'TOTAL', {m} FROM {TABLE} WHERE {where} GROUP BY GEO
        ORDER BY CASE GEO {GEO_CASE} ELSE 10 END,
                 CASE CHANNEL WHEN 'TOTAL' THEN 99 ELSE 1 END, CHANNEL
    """)

@st.cache_data(ttl=300, show_spinner=False)
def get_view1_spark(where, sfx):
    """Daily sales per GEO×CHANNEL for sparkline column."""
    return run_query(f"""
        SELECT GEO, CHANNEL, DAY,
               ROUND(SUM(SALES_ACTUAL_{sfx}),0) AS SALES_ACT
        FROM {TABLE} WHERE {where}
        GROUP BY GEO, CHANNEL, DAY
        ORDER BY DAY
    """)

@st.cache_data(ttl=300, show_spinner=False)
def get_fm_budget_v1(where_fm, sfx):
    return run_query(f"""
        SELECT GEO, CHANNEL,
            ROUND(SUM(SALES_BUDGET_{sfx}),0) AS FM_SALES_BUD,
            ROUND(SUM(CM2_BUDGET_{sfx}),0)   AS FM_CM2_BUD
        FROM {TABLE} WHERE {where_fm} GROUP BY GEO, CHANNEL
        UNION ALL
        SELECT GEO, 'TOTAL',
            ROUND(SUM(SALES_BUDGET_{sfx}),0),
            ROUND(SUM(CM2_BUDGET_{sfx}),0)
        FROM {TABLE} WHERE {where_fm} GROUP BY GEO
    """)

@st.cache_data(ttl=300, show_spinner=False)
def get_view2(where, sfx):
    return run_query(f"""
        SELECT COALESCE(NULLIF(SUB_CATEGORY,''),'(untagged)') AS SUB_CATEGORY,
            ROUND(SUM(SALES_BUDGET_{sfx}),0)  AS SALES_BUD,
            ROUND(SUM(SALES_ACTUAL_{sfx}),0)  AS SALES_ACT,
            ROUND(SUM(SALES_ACTUAL_{sfx})/NULLIF(SUM(SALES_BUDGET_{sfx}),0)*100,1) AS REV_PCT,
            ROUND(SUM(CM1_BUDGET_{sfx}),0)    AS CM1_BUD,
            ROUND(SUM(CM1_ACTUAL_{sfx}),0)    AS CM1_ACT,
            ROUND(SUM(CM2_BUDGET_{sfx}),0)    AS CM2_BUD,
            ROUND(SUM(CM2_ACTUAL_{sfx}),0)    AS CM2_ACT,
            ROUND(SUM(CM2_ACTUAL_{sfx})-SUM(CM2_BUDGET_{sfx}),0) AS CM2_VAR,
            ROUND(SUM(CM2_ACTUAL_{sfx})/NULLIF(SUM(CM2_BUDGET_{sfx}),0)*100,1) AS CM2_ABS_ACHVD_PCT
        FROM {TABLE} WHERE {where}
        GROUP BY COALESCE(NULLIF(SUB_CATEGORY,''),'(untagged)')
        UNION ALL
        SELECT 'GRAND TOTAL',
            ROUND(SUM(SALES_BUDGET_{sfx}),0),
            ROUND(SUM(SALES_ACTUAL_{sfx}),0),
            ROUND(SUM(SALES_ACTUAL_{sfx})/NULLIF(SUM(SALES_BUDGET_{sfx}),0)*100,1),
            ROUND(SUM(CM1_BUDGET_{sfx}),0),
            ROUND(SUM(CM1_ACTUAL_{sfx}),0),
            ROUND(SUM(CM2_BUDGET_{sfx}),0),
            ROUND(SUM(CM2_ACTUAL_{sfx}),0),
            ROUND(SUM(CM2_ACTUAL_{sfx})-SUM(CM2_BUDGET_{sfx}),0),
            ROUND(SUM(CM2_ACTUAL_{sfx})/NULLIF(SUM(CM2_BUDGET_{sfx}),0)*100,1)
        FROM {TABLE} WHERE {where}
        ORDER BY CASE SUB_CATEGORY WHEN 'GRAND TOTAL' THEN 9999 ELSE 1 END, SALES_BUD DESC NULLS LAST
    """)

@st.cache_data(ttl=300, show_spinner=False)
def get_fm_budget_v2(where_fm, sfx):
    return run_query(f"""
        SELECT COALESCE(NULLIF(SUB_CATEGORY,''),'(untagged)') AS SUB_CATEGORY,
            ROUND(SUM(SALES_BUDGET_{sfx}),0) AS FM_SALES_BUD,
            ROUND(SUM(CM2_BUDGET_{sfx}),0)   AS FM_CM2_BUD
        FROM {TABLE} WHERE {where_fm}
        GROUP BY COALESCE(NULLIF(SUB_CATEGORY,''),'(untagged)')
        UNION ALL
        SELECT 'GRAND TOTAL',
            ROUND(SUM(SALES_BUDGET_{sfx}),0),
            ROUND(SUM(CM2_BUDGET_{sfx}),0)
        FROM {TABLE} WHERE {where_fm}
    """)

@st.cache_data(ttl=300, show_spinner=False)
def get_asin_data(where, geo, sub_cat, sfx):
    esc = sub_cat.replace("'","''")
    if sub_cat == "(untagged)":
        subcat_filter = "COALESCE(NULLIF(p.SUB_CATEGORY,''),'(untagged)') = '(untagged)'"
    else:
        subcat_filter = f"UPPER(TRIM(COALESCE(p.SUB_CATEGORY,''))) = UPPER(TRIM('{esc}'))"
    return run_query(f"""
        SELECT
            SPLIT_PART(p.ASIN,' ',1)                                                AS ASIN,
            COALESCE(MAX(NULLIF(p.COMMON_SKU_DESCRIPTION,'')),MAX(p.ASIN))          AS PRODUCT_NAME,
            MAX(p.BRAND)                                                             AS BRAND,
            MAX(p.CHANNEL)                                                           AS CHANNEL,
            -- Budget
            ROUND(SUM(p.QTY_BUDGET),0)                                              AS BUD_UNITS,
            ROUND(SUM(p.SALES_BUDGET_{sfx}),0)                                      AS BUD_REVENUE,
            ROUND(SUM(p.SALES_BUDGET_{sfx})/NULLIF(SUM(p.QTY_BUDGET),0),2)         AS BUD_ASP,
            ROUND(SUM(p.CM1_BUDGET_{sfx})/NULLIF(SUM(p.SALES_BUDGET_{sfx}),0)*100,1) AS BUD_CM1_PCT,
            ROUND(SUM(p.PM_SPEND_BUDGET_{sfx})/NULLIF(SUM(p.SALES_BUDGET_{sfx}),0)*100,1) AS BUD_ACOS_PCT,
            ROUND(SUM(p.CM2_BUDGET_{sfx})/NULLIF(SUM(p.SALES_BUDGET_{sfx}),0)*100,1) AS BUD_CM2_PCT,
            -- P&L Actuals
            ROUND(SUM(p.QTY_ACTUAL),0)                                              AS ACT_UNITS,
            ROUND(SUM(p.SALES_ACTUAL_{sfx}),0)                                      AS ACT_REVENUE,
            ROUND(SUM(p.SALES_ACTUAL_{sfx})/NULLIF(SUM(p.QTY_ACTUAL),0),2)         AS ACT_ASP,
            ROUND(SUM(p.CM1_ACTUAL_{sfx})/NULLIF(SUM(p.SALES_ACTUAL_{sfx}),0)*100,1) AS ACT_CM1_PCT,
            ROUND(SUM(p.PM_SPEND_ACTUAL_{sfx}),0)                                   AS ACT_SPEND,
            ROUND(SUM(p.PM_SPEND_ACTUAL_{sfx})/NULLIF(SUM(p.SALES_ACTUAL_{sfx}),0)*100,1) AS ACT_ACOS_PCT,
            ROUND(SUM(p.CM2_ACTUAL_{sfx})/NULLIF(SUM(p.SALES_ACTUAL_{sfx}),0)*100,1) AS ACT_CM2_PCT,
            ROUND(SUM(p.CM2_ACTUAL_{sfx}),0)                                        AS ACT_CM2_ABS,
            ROUND(SUM(p.SALES_ACTUAL_{sfx})/NULLIF(SUM(p.SALES_BUDGET_{sfx}),0)*100,1) AS REV_ACHVD_PCT,
            -- Marketing (paid ads)
            COALESCE(ROUND(SUM(m.SPEND),0),0)                                       AS PAID_SPEND,
            COALESCE(ROUND(SUM(m.AD_SALES),0),0)                                    AS PAID_REVENUE,
            COALESCE(ROUND(SUM(m.IMPRESSIONS),0),0)                                 AS IMPRESSIONS,
            COALESCE(ROUND(SUM(m.CLICKS),0),0)                                      AS CLICKS,
            COALESCE(ROUND(SUM(m.CONVERSIONS),0),0)                                 AS PAID_UNITS,
            ROUND(SUM(m.CLICKS)/NULLIF(SUM(m.IMPRESSIONS),0)*100,2)                 AS CTR_PCT,
            ROUND(SUM(m.SPEND)/NULLIF(SUM(m.CLICKS),0),2)                           AS CPC,
            ROUND(SUM(m.AD_SALES)/NULLIF(SUM(m.SPEND),0),2)                         AS PACOS,
            ROUND(SUM(m.SPEND)/NULLIF(SUM(m.AD_SALES),0)*100,1)                     AS AD_ACOS_PCT,
            ROUND(SUM(m.AD_SALES)/NULLIF(SUM(p.SALES_ACTUAL_{sfx}),0)*100,1)        AS PCT_PAID_SALES,
            ROUND(SUM(m.CONVERSIONS)/NULLIF(SUM(m.CLICKS),0)*100,2)                 AS CONV_RATE_PCT
        FROM {TABLE} p
        LEFT JOIN {MKTG} m
            ON p.DAY = m.DAY
            AND SPLIT_PART(p.ASIN,' ',1) = m.ASIN
            AND p.GEO = m.GEO
        WHERE p.DAY BETWEEN '{d_from}' AND '{d_to}'
            AND p.GEO = '{geo}'
            AND {GEO_EXCL.replace('GEO','p.GEO')}
            AND {subcat_filter}
            AND p.ASIN IS NOT NULL AND p.ASIN != ''
        GROUP BY SPLIT_PART(p.ASIN,' ',1)
        HAVING SUM(p.SALES_ACTUAL_{sfx}) > 0 OR SUM(m.SPEND) > 0
        ORDER BY SUM(p.SALES_ACTUAL_{sfx}) DESC NULLS LAST
        LIMIT 200
    """)

# ── P&L Statement helpers ────────────────────────────────────────────────────
_PNL_LINES = [
    ("Sales",               "total",    "SALES"),
    ("(-) COGS",            "cost",     "COGS"),
    ("(-) Additional Duty", "cost",     "ADDITIONAL_DUTY"),
    ("= CM1",               "subtotal", "CM1"),
    ("(-) Outbound",        "cost",     "OUTBOUND"),
    ("(-) 3PL",             "cost",     "THREE_PL"),
    ("(-) Storage",         "cost",     "STORAGE"),
    ("(-) Last Mile",       "cost",     "LAST_MILE"),
    ("(-) Commission",      "cost",     "COMMISSION"),
    ("= CM2 (pre-mkt)",     "subtotal", "CM2_PRE_MKT"),
    ("(-) PM Spend",        "cost",     "PM_SPEND"),
    ("= CM2",               "total",    "CM2"),
]

@st.cache_data(ttl=3600)
def discover_pnl_cols():
    df = run_query("""
        SELECT UPPER(COLUMN_NAME) AS COL
        FROM information_schema.columns
        WHERE UPPER(TABLE_CATALOG) = 'VAHDAM_DB'
          AND UPPER(TABLE_SCHEMA)  = 'MAPLEMONK'
          AND UPPER(TABLE_NAME)    = 'VAHDAM_AMAZON_PNL_OVERALL_FY27_ONWARDS'
    """)
    return frozenset(df["COL"].tolist())

def _pnl_metric_sql(prefixes, sfx, with_alias=True):
    all_cols = discover_pnl_cols()
    parts = []
    for pfx in prefixes:
        for kind, short in [("ACTUAL", "ACT"), ("BUDGET", "BUD")]:
            col  = f"{pfx}_{kind}_{sfx}"
            expr = f"ROUND(SUM({col}),0)" if col in all_cols else "CAST(NULL AS NUMBER)"
            parts.append(f"{expr} AS {pfx}_{short}" if with_alias else expr)
    return ", ".join(parts)

@st.cache_data(ttl=300, show_spinner=False)
def get_pnl_agg(where, sfx):
    sel = _pnl_metric_sql([p for _, _, p in _PNL_LINES], sfx)
    return run_query(f"SELECT {sel} FROM {TABLE} WHERE {where}")

@st.cache_data(ttl=300, show_spinner=False)
def get_pnl_daily(where, sfx):
    sel = _pnl_metric_sql(["SALES", "CM1", "CM2", "PM_SPEND"], sfx)
    return run_query(f"SELECT DAY, {sel} FROM {TABLE} WHERE {where} GROUP BY DAY ORDER BY DAY")

@st.cache_data(ttl=300, show_spinner=False)
def get_pnl_category(where, sfx):
    pfxs  = ["SALES", "CM1", "CM2", "PM_SPEND"]
    sel   = _pnl_metric_sql(pfxs, sfx)
    no_al = _pnl_metric_sql(pfxs, sfx, with_alias=False)
    return run_query(f"""
        SELECT COALESCE(NULLIF(CATEGORY,''),'(untagged)') AS CATEGORY, {sel}
        FROM {TABLE} WHERE {where}
        GROUP BY COALESCE(NULLIF(CATEGORY,''),'(untagged)')
        UNION ALL
        SELECT 'GRAND TOTAL', {no_al} FROM {TABLE} WHERE {where}
        ORDER BY CASE CATEGORY WHEN 'GRAND TOTAL' THEN 9999 ELSE 1 END,
                 SALES_ACT DESC NULLS LAST
    """)

@st.cache_data(ttl=300, show_spinner=False)
def get_pnl_channel(where, sfx):
    pfxs  = ["SALES", "CM1", "CM2", "PM_SPEND"]
    sel   = _pnl_metric_sql(pfxs, sfx)
    no_al = _pnl_metric_sql(pfxs, sfx, with_alias=False)
    return run_query(f"""
        SELECT REPLACE(COALESCE(NULLIF(CHANNEL,''),'(unknown)'),'_',' ') AS CHANNEL, {sel}
        FROM {TABLE} WHERE {where} AND COALESCE(CHANNEL,'') <> 'TOTAL'
        GROUP BY CHANNEL
        UNION ALL
        SELECT 'GRAND TOTAL', {no_al} FROM {TABLE} WHERE {where}
            AND COALESCE(CHANNEL,'') <> 'TOTAL'
        ORDER BY CASE CHANNEL WHEN 'GRAND TOTAL' THEN 9999 ELSE 1 END,
                 SALES_ACT DESC NULLS LAST
    """)

@st.cache_data(ttl=300, show_spinner=False)
def get_pnl_geo(where, sfx):
    pfxs  = ["SALES", "CM1", "CM2", "PM_SPEND"]
    sel   = _pnl_metric_sql(pfxs, sfx)
    no_al = _pnl_metric_sql(pfxs, sfx, with_alias=False)
    return run_query(f"""
        SELECT COALESCE(NULLIF(GEO,''),'(unknown)') AS GEO, {sel}
        FROM {TABLE} WHERE {where} AND COALESCE(CHANNEL,'') <> 'TOTAL'
        GROUP BY GEO
        UNION ALL
        SELECT 'GRAND TOTAL', {no_al} FROM {TABLE} WHERE {where}
            AND COALESCE(CHANNEL,'') <> 'TOTAL'
        ORDER BY (CASE WHEN GEO = 'GRAND TOTAL' THEN 1 ELSE 0 END),
                 SALES_ACT DESC NULLS LAST
    """)

@st.cache_data(ttl=300, show_spinner=False)
def get_sku_lookup(term, d1, d2, sfx):
    t = term.strip().replace("'", "''")
    return run_query(f"""
        SELECT
            SPLIT_PART(ASIN,' ',1)                                                AS ASIN,
            COALESCE(MAX(NULLIF(COMMON_SKU_DESCRIPTION,'')), MAX(ASIN))           AS PRODUCT,
            MAX(BRAND)                                                             AS BRAND,
            MAX(GEO)                                                               AS GEO,
            MAX(COALESCE(NULLIF(SUB_CATEGORY,''),'—'))                            AS SUB_CAT,
            ROUND(SUM(SALES_ACTUAL_{sfx}),0)                                      AS ACT_REV,
            ROUND(SUM(SALES_BUDGET_{sfx}),0)                                      AS BUD_REV,
            ROUND(SUM(SALES_ACTUAL_{sfx})/NULLIF(SUM(SALES_BUDGET_{sfx}),0)*100,1) AS REV_PCT,
            ROUND(SUM(CM2_ACTUAL_{sfx}),0)                                        AS CM2_ABS
        FROM {TABLE}
        WHERE DAY BETWEEN '{d1}' AND '{d2}' AND {GEO_EXCL}
          AND (UPPER(SPLIT_PART(ASIN,' ',1)) LIKE UPPER('%{t}%')
               OR UPPER(COALESCE(COMMON_SKU_DESCRIPTION,'')) LIKE UPPER('%{t}%'))
        GROUP BY SPLIT_PART(ASIN,' ',1)
        ORDER BY SUM(SALES_ACTUAL_{sfx}) DESC NULLS LAST
        LIMIT 50
    """)

def forecast_card(sales_act, sales_bud, days_elapsed_v, total_days_v):
    """Forecast EOM pace card — projects current pace to end of month."""
    s_act = _f(sales_act); s_bud = _f(sales_bud)
    if s_act is None or days_elapsed_v <= 0 or total_days_v <= 0: return ""
    daily_pace = s_act / days_elapsed_v
    forecast   = daily_pace * total_days_v
    delta_abs  = (forecast - s_bud) if s_bud is not None else None
    delta_pct  = ((forecast - s_bud) / abs(s_bud) * 100) if (s_bud and s_bud != 0) else None
    pace_html = ""
    if delta_pct is not None:
        if   delta_pct >=  2: cls, ico = "pace-good", "🟢"
        elif delta_pct <= -2: cls, ico = "pace-bad",  "🔴"
        else:                 cls, ico = "pace-warn", "🟡"
        pace_html = (f'<div class="forecast-pace {cls}">{ico} '
                     f'{("+" if delta_pct >= 0 else "")}{delta_pct:.1f}% vs FM Budget '
                     f'({fmt_lakhs(delta_abs, signed=True)})</div>')
    bud_line = (f'<div class="forecast-sub">FM Bud: {fmt_lakhs(s_bud)}'
                f' &nbsp;·&nbsp; Pace: {fmt_lakhs(daily_pace)}/day</div>') if s_bud is not None else ""
    return (f'<div class="forecast-card">'
            f'<div class="forecast-label">🔮 Forecast End-of-Month</div>'
            f'<div class="forecast-val">{fmt_lakhs(forecast)}</div>'
            f'{bud_line}{pace_html}</div>')


def render_breadcrumbs(segments):
    """Render clickable breadcrumbs.

    segments: list of (label, view_state, geo, subcat) tuples — last entry is the
    current page (rendered as plain text, not clickable). All earlier entries are
    rendered as tertiary buttons that navigate when clicked.
    """
    if not segments: return
    n = len(segments)
    # Each segment col is sized to comfortably fit the label.
    # Streamlit's tertiary button has built-in padding; we need extra room.
    col_specs = []
    for i, seg in enumerate(segments):
        w = max(4, int(len(seg[0]) * 1.8) + 3)
        col_specs.append(w)
        if i < n - 1:
            col_specs.append(2)  # separator
    col_specs.append(60)  # spacer pushes breadcrumbs to the left
    cols = st.columns(col_specs, gap="small")
    cidx = 0
    for i, (label, view_state, geo, subcat) in enumerate(segments):
        with cols[cidx]:
            if i == n - 1:
                # current page — non-clickable, slightly emphasized
                st.markdown(
                    f'<div style="font-size:12px;color:#004A2B;font-weight:700;'
                    f'letter-spacing:0.4px;text-transform:uppercase;'
                    f'padding-top:6px;white-space:nowrap;">{label}</div>',
                    unsafe_allow_html=True)
            else:
                if st.button(label, key=f"crumb_{i}_{label}",
                             type="tertiary",
                             use_container_width=False):
                    st.session_state.view = view_state
                    if geo is not None:    st.session_state.selected_geo = geo
                    if subcat is not None: st.session_state.selected_subcat = subcat
                    st.rerun()
        cidx += 1
        if i < n - 1:
            with cols[cidx]:
                st.markdown('<div style="font-size:14px;color:#d6ccba;'
                            'padding-top:4px;text-align:center;">›</div>',
                            unsafe_allow_html=True)
            cidx += 1


## ── Metric definitions (#5) ──
METRIC_DEFS = {
    "SALES":          "Sales = SUM(Sales Actual). Total gross revenue for the period.",
    "REV_BUDGET":     "Revenue Budget = SUM(Sales Budget) for the period.",
    "REV_PCT":        "Rev % = Sales Actual ÷ Sales Budget × 100. >100% = above plan.",
    "CM1":            "CM1 = Contribution Margin 1 = Sales − COGS − Additional Duty.\n"
                      "CM1% = CM1 ÷ Sales × 100.",
    "ACOS":           "ACoS = Advertising Cost of Sales = PM Spend ÷ Sales × 100.\n"
                      "Lower is better (ad efficiency). <20% = efficient, >35% = unhealthy.",
    "CM2":            "CM2 = CM1 − Outbound − 3PL − Storage − Last Mile − Commission − PM Spend.\n"
                      "CM2% = CM2 ÷ Sales × 100. The bottom-line margin after all marketplace costs.",
    "CM2_ABS":        "CM2 Absolute = CM2 in rupee terms. The actual profit contribution.",
    "FORECAST_EOM":   "Forecast EOM = (Sales-to-date ÷ days elapsed) × total days in month.\n"
                      "Linear extrapolation of current pace to month-end.",
    "PACE":           "Pace = Sales Actual ÷ days elapsed (per day average for the period).",
}


def hero_card(label, value, sub=None, delta_pct=None):
    """Big hero KPI card for CEO landing."""
    parts = [f'<div class="hero-card">'
             f'<div class="hero-label">{label}</div>'
             f'<div class="hero-value">{value}</div>']
    if sub: parts.append(f'<div class="hero-sub">{sub}</div>')
    if delta_pct is not None:
        d = _f(delta_pct)
        if d is not None:
            cls = "hero-up" if d >= 0 else "hero-down"
            arrow = "▲" if d >= 0 else "▼"
            parts.append(f'<div class="hero-delta {cls}">{arrow} {abs(d):.1f}% vs prior period</div>')
    parts.append('</div>')
    return "".join(parts)


def build_narrative(k, view1_df=None):
    """Auto-generated 1-2 sentence summary from KPI row + optional GEO breakdown."""
    sales_act = _f(k.get("SALES_ACT"))
    rev_delta = _f(k.get("REV_DELTA"))
    cm2_pct   = _f(k.get("CM2_ACT"))
    cm2_delta = _f(k.get("CM2_DELTA"))
    cm2_abs   = _f(k.get("CM2_ABS_ACT"))
    cm2_abs_d = _f(k.get("CM2_ABS_DELTA"))
    if sales_act is None: return None

    if rev_delta is None: tone, color = "tracking budget", "nl"
    elif rev_delta >= 5:  tone, color = f"<span class='nw'>{rev_delta:+.1f}% ahead of budget</span>", "nw"
    elif rev_delta <= -5: tone, color = f"<span class='nd'>{rev_delta:+.1f}% behind budget</span>", "nd"
    else:                 tone, color = f"<span class='nl'>{rev_delta:+.1f}% vs budget</span>", "nl"

    parts = [f"Sales are <b>{fmt_lakhs(sales_act)}</b>, {tone}."]

    if view1_df is not None and not view1_df.empty:
        totals = view1_df[view1_df["CHANNEL"] == "TOTAL"].copy()
        if not totals.empty:
            totals["REV_PCT_n"] = pd.to_numeric(totals["REV_PCT"], errors="coerce")
            winners = totals.nlargest(1, "REV_PCT_n")
            losers  = totals.nsmallest(1, "REV_PCT_n")
            geo_parts = []
            if not winners.empty and _f(winners.iloc[0]["REV_PCT_n"]) is not None:
                w = winners.iloc[0]
                geo_parts.append(f"driven by <b>{w['GEO']}</b> "
                                 f"(<span class='nw'>{_f(w['REV_PCT_n']):.0f}%</span>)")
            if not losers.empty and _f(losers.iloc[0]["REV_PCT_n"]) is not None:
                l = losers.iloc[0]
                if l['GEO'] != (winners.iloc[0]['GEO'] if not winners.empty else None):
                    geo_parts.append(f"watch <b>{l['GEO']}</b> "
                                     f"(<span class='nd'>{_f(l['REV_PCT_n']):.0f}%</span>)")
            if geo_parts:
                parts.append(" " + ", ".join(geo_parts) + ".")

    if cm2_pct is not None:
        cm_tone = ""
        if cm2_delta is not None:
            cm_tone = (f" (<span class='nw'>{cm2_delta:+.1f}pp vs Bud</span>)" if cm2_delta >= 0
                       else f" (<span class='nd'>{cm2_delta:+.1f}pp vs Bud</span>)")
        if cm2_abs is not None:
            parts.append(f" CM2 margin is <b>{cm2_pct:.1f}%</b>{cm_tone}, "
                         f"contributing <b>{fmt_lakhs(cm2_abs)}</b> in absolute terms.")
        else:
            parts.append(f" CM2 margin is <b>{cm2_pct:.1f}%</b>{cm_tone}.")
    return "".join(parts)


def top_movers_chips(view1_df, n=3):
    """Generate top winners/laggards from GEO TOTAL rows."""
    if view1_df is None or view1_df.empty: return ""
    totals = view1_df[view1_df["CHANNEL"] == "TOTAL"].copy()
    if totals.empty: return ""
    totals["REV_PCT_n"] = pd.to_numeric(totals["REV_PCT"], errors="coerce")
    totals = totals.dropna(subset=["REV_PCT_n"])
    if totals.empty: return ""
    winners = totals.nlargest(n, "REV_PCT_n")
    losers  = totals.nsmallest(n, "REV_PCT_n").iloc[::-1]
    chips = []
    for _, r in winners.iterrows():
        if r["REV_PCT_n"] >= 100:
            chips.append(f'<span class="mover-chip mover-up">📈 {r["GEO"]} '
                         f'<b>{r["REV_PCT_n"]:.0f}%</b></span>')
    for _, r in losers.iterrows():
        if r["REV_PCT_n"] < 95:
            chips.append(f'<span class="mover-chip mover-down">📉 {r["GEO"]} '
                         f'<b>{r["REV_PCT_n"]:.0f}%</b></span>')
    if not chips: return ""
    return f'<div class="movers-row">{"".join(chips)}</div>'


def strip_card(label, value, sub=None, delta=None):
    """Compact KPI card matching the P&L summary strip style. Reusable across views."""
    delta_html = ""
    if delta is not None:
        d = _f(delta)
        if d is not None:
            cls = "delta-up" if d >= 0 else "delta-dn"
            arrow = "▲" if d >= 0 else "▼"
            delta_html = f'<div class="kpi-delta {cls}">{arrow} {abs(d):.1f}%</div>'
    sub_html = f'<div class="pnl-strip-sub">{sub}</div>' if sub else ""
    return (f'<div class="pnl-strip">'
            f'<div class="pnl-strip-label">{label}</div>'
            f'<div class="pnl-strip-val">{value}</div>'
            f'{sub_html}{delta_html}</div>')


# ── Goal-achievement gauges (#4) ──
def build_gauge(pct, title, target_pct=100, height=180):
    """Half-doughnut gauge in Vahdam brand colors. pct can be None."""
    if not HAS_PLOTLY: return None
    v = _f(pct)
    if v is None: v = 0
    v_clamp = max(0, min(v, 150))
    # threshold color
    if v >= target_pct:        bar = "#1a7a3e"
    elif v >= target_pct * 0.9: bar = "#AB8743"
    else:                       bar = "#8b1a1a"
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=v_clamp,
        number={"suffix": "%", "font": {"size": 28, "color": "#004A2B"}},
        gauge={
            "shape": "angular",
            "axis": {"range": [0, 150], "tickwidth": 0,
                     "tickfont": {"size": 9, "color": "#7a6a50"}},
            "bar":  {"color": bar, "thickness": 0.32},
            "bgcolor": "#FBF5EA",
            "borderwidth": 0,
            "steps": [
                {"range": [0, target_pct*0.9], "color": "rgba(139,26,26,0.10)"},
                {"range": [target_pct*0.9, target_pct], "color": "rgba(171,135,67,0.15)"},
                {"range": [target_pct, 150], "color": "rgba(26,122,62,0.12)"},
            ],
            "threshold": {
                "line": {"color": "#004A2B", "width": 3},
                "thickness": 0.85, "value": target_pct,
            },
        },
        domain={"x": [0, 1], "y": [0, 1]},
    ))
    fig.update_layout(
        title=dict(text=f"<b>{title}</b>", x=0.5, xanchor="center",
                   font=dict(size=12, color="#004A2B")),
        paper_bgcolor="#FBF5EA",
        height=height, margin=dict(l=20, r=20, t=40, b=20),
    )
    return fig


# ── Count-up number animation (#13) ──
def countup_number(target_value, fmt_str="{}", duration_ms=900, html_id=None):
    """Returns HTML with embedded JS that animates from 0 to target_value.
    fmt_str example: '₹{}Cr' (one {} placeholder for the number)."""
    import time as _t
    if html_id is None:
        html_id = f"cu_{int(_t.time() * 1000) % 1_000_000}_{abs(hash(target_value)) % 100000}"
    safe_target = _f(target_value) or 0
    return (f'<span class="countup" id="{html_id}">'
            f'{fmt_str.replace("{}", f"{safe_target:.2f}")}</span>'
            f'<script>(function(){{'
            f'var el=document.getElementById("{html_id}");'
            f'if(!el)return;'
            f'var t={safe_target},s=Date.now(),d={duration_ms};'
            f'function tick(){{'
            f'var p=Math.min(1,(Date.now()-s)/d);'
            f'var e=1-Math.pow(1-p,3);'
            f'el.textContent={repr(fmt_str)}.replace("{{}}",(t*e).toFixed(2));'
            f'if(p<1)requestAnimationFrame(tick);'
            f'}}tick();'
            f'}})();</script>')


# ── In-app alert banners (#18) ──
def render_alerts(view1_df, kpi_row, agg_label="GEO"):
    """Render alert banners based on data conditions."""
    alerts = []
    if view1_df is not None and not view1_df.empty:
        totals = view1_df[view1_df["CHANNEL"] == "TOTAL"].copy()
        totals["REV_PCT_n"] = pd.to_numeric(totals["REV_PCT"], errors="coerce")
        totals = totals.dropna(subset=["REV_PCT_n"])
        critical = totals[totals["REV_PCT_n"] < 80]
        if not critical.empty:
            geos = ", ".join(critical["GEO"].head(3).tolist())
            alerts.append(("danger", f"🚨 Critical: {len(critical)} {agg_label}"
                                       f"{'s' if len(critical) != 1 else ''} below 80% of "
                                       f"budget — {geos}"))
        warn = totals[(totals["REV_PCT_n"] >= 80) & (totals["REV_PCT_n"] < 90)]
        if not warn.empty:
            geos = ", ".join(warn["GEO"].head(3).tolist())
            alerts.append(("warn", f"⚠️ Watch: {len(warn)} {agg_label}"
                                    f"{'s' if len(warn) != 1 else ''} between "
                                    f"80–90% of budget — {geos}"))
    if kpi_row is not None:
        acos_delta = _f(kpi_row.get("ACOS_DELTA"))
        if acos_delta is not None and acos_delta > 3:
            alerts.append(("warn", f"📈 ACoS is {acos_delta:+.1f}pp above budget — "
                                    "review ad spend efficiency."))
        cm2_delta = _f(kpi_row.get("CM2_DELTA"))
        if cm2_delta is not None and cm2_delta < -2:
            alerts.append(("danger", f"💸 CM2 margin is {cm2_delta:+.1f}pp below budget — "
                                      "profitability under pressure."))
    if not alerts: return ""
    html_parts = ['<div class="alerts-row">']
    for kind, msg in alerts:
        html_parts.append(f'<div class="alert-banner alert-{kind}">{msg}</div>')
    html_parts.append('</div>')
    return "".join(html_parts)


# ── Variance attribution (#20) ──
def build_variance_chart(view1_df):
    """Stacked horizontal bar showing each GEO's contribution to sales variance vs budget."""
    if not HAS_PLOTLY or view1_df is None or view1_df.empty: return None
    totals = view1_df[view1_df["CHANNEL"] == "TOTAL"].copy()
    totals["ACT_n"] = pd.to_numeric(totals["SALES_ACT"], errors="coerce")
    totals["BUD_n"] = pd.to_numeric(totals["SALES_BUD"], errors="coerce")
    totals = totals.dropna(subset=["ACT_n"])
    if totals.empty: return None
    totals["VAR_n"] = totals["ACT_n"].fillna(0) - totals["BUD_n"].fillna(0)
    totals = totals[totals["VAR_n"].abs() > 0].copy()
    if totals.empty: return None
    totals = totals.sort_values("VAR_n", ascending=True)
    # Auto-scale unit
    peak = totals["VAR_n"].abs().max()
    if   peak >= 1e7: div, unit = 1e7, "Cr"
    elif peak >= 1e5: div, unit = 1e5, "L"
    elif peak >= 1e3: div, unit = 1e3, "K"
    else:             div, unit = 1, ""
    totals["VAR_scaled"] = totals["VAR_n"] / div
    colors = ["#1a7a3e" if v >= 0 else "#8b1a1a" for v in totals["VAR_n"]]
    fig = go.Figure(go.Bar(
        x=totals["VAR_scaled"], y=totals["GEO"],
        orientation="h",
        marker=dict(color=colors, line=dict(color="rgba(0,74,43,0.4)", width=1)),
        text=[fmt_lakhs(v, signed=True) for v in totals["VAR_n"]],
        textposition="outside",
        hovertemplate=("<b>%{y}</b><br>"
                       f"Variance: %{{text}}<br>"
                       f"Actual: %{{customdata[0]}}<br>"
                       f"Budget: %{{customdata[1]}}<extra></extra>"),
        customdata=list(zip(totals["ACT_n"].apply(fmt_lakhs),
                            totals["BUD_n"].apply(fmt_lakhs))),
    ))
    fig.update_layout(
        title=dict(text=f"<b>Sales Variance vs Budget by Country</b> (₹ {unit})",
                   font=dict(size=14, color="#004A2B")),
        plot_bgcolor="#FBF5EA", paper_bgcolor="#FBF5EA",
        font=dict(family="Arial", color="#171717"),
        height=max(220, 60 + len(totals) * 32),
        margin=dict(l=60, r=80, t=50, b=40),
        showlegend=False,
    )
    fig.update_xaxes(title_text=f"Variance (₹ {unit})",
                      gridcolor="rgba(171,135,67,0.18)",
                      zerolinecolor="rgba(0,74,43,0.5)", zerolinewidth=2)
    fig.update_yaxes(title_text="", gridcolor="rgba(171,135,67,0.18)")
    return fig


# ── URL params persistence (#19) ──
def sync_state_from_url():
    """Read URL params on initial load and seed session_state."""
    qp = st.query_params
    if "view" in qp and qp["view"] in {"ceo","overview","subcategory","asin","pnl"}:
        st.session_state.view = qp["view"]
    if "geo" in qp:    st.session_state.selected_geo    = qp["geo"]
    if "subcat" in qp: st.session_state.selected_subcat = qp["subcat"]
    if "preset" in qp and "date_preset" not in st.session_state:
        st.session_state.date_preset = qp["preset"]
    if "sku" in qp and "sku_search" not in st.session_state:
        st.session_state.sku_search = qp["sku"]


def write_state_to_url(view, geo, subcat, preset, sku):
    """Mirror current session state to URL query params (so the URL can be shared)."""
    qp = {}
    if view:                       qp["view"]   = view
    if geo:                        qp["geo"]    = geo
    if subcat:                     qp["subcat"] = subcat
    if preset and preset != "MTD": qp["preset"] = preset
    if sku and sku.strip():        qp["sku"]    = sku.strip()
    st.query_params.update(qp)


# ── AI insights (#17, optional) ──
def ai_available():
    try:
        return "anthropic" in st.secrets and bool(st.secrets["anthropic"].get("api_key"))
    except Exception:
        return False


@st.cache_data(ttl=180, show_spinner=False)
def ask_ai(question, context_str):
    """Send question + KPI context to Claude. Returns markdown string."""
    if not ai_available(): return None
    try:
        import urllib.request, urllib.error, json
        api_key = st.secrets["anthropic"]["api_key"]
        prompt = (f"You are a senior P&L analyst for Vahdam India, a tea brand "
                  f"selling on Amazon globally. Answer in 2-4 short sentences with "
                  f"specific numbers from the data. Be direct and actionable.\n\n"
                  f"DATA:\n{context_str}\n\nQUESTION: {question}\n\nANSWER:")
        body = json.dumps({
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 400,
            "messages": [{"role": "user", "content": prompt}],
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=body, method="POST",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data["content"][0]["text"]
    except Exception as e:
        return f"_AI error: {e}_"


def fmt_indian(v, signed=False):
    """Indian number format: 1,04,09,835"""
    n = _f(v)
    if n is None: return "—"
    neg = n < 0
    vi  = int(round(abs(n)))
    s   = str(vi)
    if len(s) <= 3:
        result = s
    else:
        result = s[-3:]
        s = s[:-3]
        while s:
            result = s[-2:] + "," + result
            s = s[:-2]
    return ("-" if neg else ("+" if (signed and n > 0) else "")) + result

def _build_waterfall(row):
    rows = []
    for label, row_type, pfx in _PNL_LINES:
        act = _f(row.get(f"{pfx}_ACT"))
        bud = _f(row.get(f"{pfx}_BUD"))
        if act is not None and bud is not None:
            var     = act - bud
            var_pct = (var / abs(bud) * 100) if bud != 0 else None
        else:
            var, var_pct = None, None
        rows.append({
            "P&L Line":       label,
            "Actual (INR)":   fmt_indian(act),
            "Budget (INR)":   fmt_indian(bud),
            "Variance (INR)": fmt_indian(var, signed=True),
            "Var %":          (f"{'+'if (var_pct or 0)>=0 else ''}{var_pct:.1f}%"
                               if var_pct is not None else "—"),
            "_type": row_type,
            "_var":  var,
            "_cost": row_type == "cost",
        })
    return rows


# ═══════════════════════════════════════════════════════════════════════════════
# VIEW 1 — GEO × Channel Overview
# ═══════════════════════════════════════════════════════════════════════════════
def render_ceo():
    """Single-screen executive summary — high signal, no scrolling required."""
    st.markdown('<div class="page-title">⭐ Executive Summary</div>',
                unsafe_allow_html=True)
    st.markdown(
        f'<div class="page-sub">{d_from.strftime("%d %b %Y")} &rarr; {d_to.strftime("%d %b %Y")}'
        f' &nbsp;&bull;&nbsp; Currency: {"INR (₹)" if use_inr else "Local"}'
        f' &nbsp;&bull;&nbsp; {_period_len} days  &nbsp;&bull;&nbsp; '
        f'<span style="color:#7a6a50">vs prior {_period_len}d: '
        f'{prev_d_from.strftime("%d %b")}–{prev_d_to.strftime("%d %b")}</span></div>',
        unsafe_allow_html=True)

    where      = build_where()
    where_prev = build_where(date_from=prev_d_from, date_to=prev_d_to)
    where_fm   = build_where(date_from=month_start, date_to=month_end)
    kpi        = get_kpis(where, sfx)
    kpi_prev   = get_kpis(where_prev, sfx)
    kpi_fm     = get_kpis(where_fm, sfx)  # full-month budget for forecast
    df         = get_view1(where, sfx)

    if kpi.empty:
        st.warning("📭 No data found for the selected filters.")
        return
    k = kpi.iloc[0]
    kp = kpi_prev.iloc[0] if not kpi_prev.empty else None
    kfm = kpi_fm.iloc[0] if not kpi_fm.empty else None

    # ── Alert banners (#18) ──
    alerts_html = render_alerts(df, k, agg_label="GEO")
    if alerts_html:
        st.markdown(alerts_html, unsafe_allow_html=True)

    # Narrative
    narrative = build_narrative(k, df if not df.empty else None)
    if narrative:
        st.markdown(f'<div class="narrative">📊 {narrative}</div>',
                    unsafe_allow_html=True)

    # ── 4 hero KPIs ──
    def _pop(key, mode="ratio"):
        if kp is None: return None
        cur, prev = _f(k.get(key)), _f(kp.get(key))
        if cur is None or prev is None or (mode == "ratio" and prev == 0): return None
        return (cur - prev) if mode == "pp" else (cur - prev) / abs(prev) * 100

    cols = st.columns(4)
    cols[0].markdown(hero_card("Sales", fmt_lakhs(k.get("SALES_ACT")),
                                f"Bud: {fmt_lakhs(k.get('SALES_BUD'))}",
                                _pop("SALES_ACT")), unsafe_allow_html=True)
    cols[1].markdown(hero_card("CM2 Absolute", fmt_lakhs(k.get("CM2_ABS_ACT")),
                                f"Bud: {fmt_lakhs(k.get('CM2_ABS_BUD'))}",
                                _pop("CM2_ABS_ACT")), unsafe_allow_html=True)
    cols[2].markdown(hero_card("CM2 Margin", fmt_pct(k.get("CM2_ACT")),
                                f"Bud: {fmt_pct(k.get('CM2_BUD'))}",
                                _pop("CM2_ACT", "pp")), unsafe_allow_html=True)
    cols[3].markdown(hero_card("Revenue vs Budget", fmt_pct(k.get("REV_PCT")),
                                f"Δ: {fmt_lakhs((_f(k.get('SALES_ACT')) or 0) - (_f(k.get('SALES_BUD')) or 0), signed=True)}",
                                None), unsafe_allow_html=True)

    # ── Forecast EOM (#9) + Goal gauges (#4) ──
    if kfm is not None and days_elapsed > 0:
        mtd_where = build_where(date_from=month_start, date_to=min(d_to, month_end))
        mtd_kpi   = get_kpis(mtd_where, sfx)
        if not mtd_kpi.empty:
            mtd_act = _f(mtd_kpi.iloc[0].get("SALES_ACT"))
            mtd_bud = _f(kfm.get("SALES_BUD"))
            fc_html = forecast_card(mtd_act, mtd_bud, days_elapsed, _total_days)
            # 4 columns: forecast card + 3 gauges
            g_cols = st.columns([2, 1, 1, 1])
            with g_cols[0]:
                if fc_html: st.markdown(fc_html, unsafe_allow_html=True)
            with g_cols[1]:
                g1 = build_gauge(_f(k.get("REV_PCT")), "Revenue vs Budget", target_pct=100)
                if g1: st.plotly_chart(g1, use_container_width=True,
                                       config={"displayModeBar": False})
            with g_cols[2]:
                cm2_act = _f(k.get("CM2_ACT")); cm2_bud = _f(k.get("CM2_BUD"))
                cm2_pct = (cm2_act / cm2_bud * 100) if (cm2_act and cm2_bud) else None
                g2 = build_gauge(cm2_pct, "CM2% vs Budget", target_pct=100)
                if g2: st.plotly_chart(g2, use_container_width=True,
                                       config={"displayModeBar": False})
            with g_cols[3]:
                acos_act = _f(k.get("ACOS_ACT")); acos_bud = _f(k.get("ACOS_BUD"))
                # Lower ACoS is better — invert: 100% means at or below budget
                if acos_act and acos_bud:
                    acos_pct = (acos_bud / acos_act * 100) if acos_act else None
                else:
                    acos_pct = None
                g3 = build_gauge(acos_pct, "Ad Efficiency", target_pct=100)
                if g3: st.plotly_chart(g3, use_container_width=True,
                                       config={"displayModeBar": False})

    # ── Top movers ──
    if not df.empty:
        movers_html = top_movers_chips(df, n=3)
        if movers_html:
            st.markdown('<div class="section-hdr" style="margin-top:18px;">'
                        'Top movers</div>', unsafe_allow_html=True)
            st.markdown(movers_html, unsafe_allow_html=True)

    # ── Best / Worst GEO callouts ──
    if not df.empty:
        totals = df[df["CHANNEL"] == "TOTAL"].copy()
        totals["REV_PCT_n"] = pd.to_numeric(totals["REV_PCT"], errors="coerce")
        totals = totals.dropna(subset=["REV_PCT_n"])
        if not totals.empty:
            best  = totals.nlargest(1,  "REV_PCT_n").iloc[0]
            worst = totals.nsmallest(1, "REV_PCT_n").iloc[0]
            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f"""
                <div class="hero-card" style="border-top-color:#1a7a3e;">
                    <div class="hero-label" style="color:#1a7a3e;">🏆 Best-performing GEO</div>
                    <div class="hero-value">{best['GEO']}</div>
                    <div class="hero-sub">Revenue: {fmt_lakhs(best['SALES_ACT'])}
                        &nbsp;·&nbsp; <b style="color:#1a7a3e;">{_f(best['REV_PCT_n']):.1f}% vs Bud</b></div>
                </div>""", unsafe_allow_html=True)
            with c2:
                st.markdown(f"""
                <div class="hero-card" style="border-top-color:#8b1a1a;">
                    <div class="hero-label" style="color:#8b1a1a;">⚠️ Needs attention</div>
                    <div class="hero-value">{worst['GEO']}</div>
                    <div class="hero-sub">Revenue: {fmt_lakhs(worst['SALES_ACT'])}
                        &nbsp;·&nbsp; <b style="color:#8b1a1a;">{_f(worst['REV_PCT_n']):.1f}% vs Bud</b></div>
                </div>""", unsafe_allow_html=True)

    # ── Daily Sales sparkline ──
    spark = get_view1_spark(where, sfx)
    if not spark.empty and HAS_PLOTLY:
        spark["DAY"] = pd.to_datetime(spark["DAY"])
        daily = spark.groupby("DAY")["SALES_ACT"].sum().reset_index()
        peak  = daily["SALES_ACT"].abs().max() or 0
        if peak >= 1e7:  div, unit = 1e7, "Cr"
        elif peak >= 1e5: div, unit = 1e5, "L"
        elif peak >= 1e3: div, unit = 1e3, "K"
        else:             div, unit = 1, ""
        fig = go.Figure(go.Scatter(
            x=daily["DAY"], y=daily["SALES_ACT"]/div,
            mode="lines+markers", fill="tozeroy",
            line=dict(color="#004A2B", width=2.5),
            marker=dict(size=5, color="#004A2B"),
            fillcolor="rgba(0,74,43,0.08)",
            hovertemplate=f"<b>%{{x|%d %b}}</b><br>{sym}%{{y:.2f}}{unit}<extra></extra>",
        ))
        fig.update_layout(
            title=dict(text=f"<b>Daily Sales</b> (₹ {unit})",
                       font=dict(size=15, color="#004A2B")),
            plot_bgcolor="#FBF5EA", paper_bgcolor="#FBF5EA",
            height=260, margin=dict(l=40, r=40, t=50, b=40),
            showlegend=False,
        )
        fig.update_xaxes(showgrid=True, gridcolor="rgba(171,135,67,0.15)")
        fig.update_yaxes(showgrid=True, gridcolor="rgba(171,135,67,0.15)",
                          title_text=f"₹ {unit}".strip())
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # ── AI Insights (#17) ──
    if ai_available():
        st.markdown('<div class="section-hdr" style="margin-top:24px;">'
                    '🤖 Ask the data <span style="font-size:12px;color:#7a6a50;'
                    'font-weight:500;">— ask a question about this period</span></div>',
                    unsafe_allow_html=True)
        q = st.text_input("Question", placeholder="e.g., Why is CA underperforming? "
                          "Which GEO has the best margins?",
                          key="ai_question", label_visibility="collapsed")
        if q and q.strip():
            context = (f"Period: {d_from} to {d_to} ({_period_len} days)\n"
                       f"Sales Actual: {fmt_lakhs(k.get('SALES_ACT'))} "
                       f"(Budget: {fmt_lakhs(k.get('SALES_BUD'))}, "
                       f"Rev%: {fmt_pct(k.get('REV_PCT'))})\n"
                       f"CM1: {fmt_pct(k.get('CM1_ACT'))} (Bud: {fmt_pct(k.get('CM1_BUD'))})\n"
                       f"CM2: {fmt_pct(k.get('CM2_ACT'))} (Bud: {fmt_pct(k.get('CM2_BUD'))})\n"
                       f"CM2 Absolute: {fmt_lakhs(k.get('CM2_ABS_ACT'))}\n"
                       f"ACoS: {fmt_pct(k.get('ACOS_ACT'))} (Bud: {fmt_pct(k.get('ACOS_BUD'))})\n")
            if not df.empty:
                totals = df[df["CHANNEL"] == "TOTAL"].copy()
                context += "\nGEO Breakdown:\n"
                for _, r in totals.iterrows():
                    context += (f"- {r['GEO']}: Sales {fmt_lakhs(r['SALES_ACT'])} "
                                f"(Bud {fmt_lakhs(r['SALES_BUD'])}, "
                                f"{fmt_pct(r['REV_PCT'])})\n")
            with st.spinner("Asking Claude…"):
                answer = ask_ai(q.strip(), context)
            if answer:
                st.markdown(f'<div class="narrative" style="border-left-color:#4a6bb8;">'
                            f'🤖 {answer.replace(chr(10), "<br>")}</div>',
                            unsafe_allow_html=True)

    # ── Share + print toolbar (#10, #19) ──
    st.markdown("---")
    write_state_to_url(st.session_state.view,
                       st.session_state.selected_geo,
                       st.session_state.selected_subcat,
                       st.session_state.get("date_preset", "MTD"),
                       st.session_state.get("sku_search", ""))
    s1, s2, s3 = st.columns([3, 3, 3])
    with s1:
        share_html = (f'<a href="#" onclick="navigator.clipboard.writeText('
                      f"window.location.href);this.innerText='✓ Copied!';"
                      f'return false;" style="display:inline-block;'
                      f'padding:8px 16px;background:#004A2B;color:#FBF5EA;'
                      f'border-radius:6px;text-decoration:none;font-weight:600;'
                      f'font-size:14px;">🔗 Copy share link</a>')
        st.markdown(share_html, unsafe_allow_html=True)
    with s2:
        st.markdown(
            '<a href="javascript:window.print()" style="display:inline-block;'
            'padding:8px 16px;background:#AB8743;color:#171717;'
            'border-radius:6px;text-decoration:none;font-weight:600;'
            'font-size:14px;">🖨️ Print / Save PDF</a>',
            unsafe_allow_html=True)
    with s3:
        _sales_txt   = fmt_lakhs(k.get("SALES_ACT"))
        _cm2pct_txt  = fmt_pct(k.get("CM2_ACT"))
        _rev_pct_txt = fmt_pct(k.get("REV_PCT"))
        mail_subject = f"Vahdam Amazon P%26L — {d_from} to {d_to}"
        mail_body    = (f"Period: {d_from} to {d_to}%0D%0A"
                        f"Sales: {_sales_txt} ({_rev_pct_txt} of Bud)%0D%0A"
                        f"CM2 Margin: {_cm2pct_txt}%0D%0A"
                        f"CM2 Absolute: {fmt_lakhs(k.get('CM2_ABS_ACT'))}%0D%0A%0D%0A"
                        f"Full dashboard: ")
        st.markdown(
            f'<a href="mailto:?subject={mail_subject}&body={mail_body}" '
            'style="display:inline-block;padding:8px 16px;background:#ffffff;'
            'color:#004A2B;border:1px solid #004A2B;border-radius:6px;'
            'text-decoration:none;font-weight:600;font-size:14px;">'
            '✉️ Email summary</a>',
            unsafe_allow_html=True)

    # ── Drill into full dashboard ──
    st.markdown("---")
    d1, d2, d3 = st.columns(3)
    with d1:
        if st.button("📊 Full Overview →", use_container_width=True, key="ceo_to_overview"):
            st.session_state.view = "overview"; st.rerun()
    with d2:
        if st.button("📋 P&L Statement →", use_container_width=True, key="ceo_to_pnl"):
            st.session_state.view = "pnl"; st.rerun()
    with d3:
        if not df.empty:
            totals = df[df["CHANNEL"] == "TOTAL"]
            if not totals.empty:
                top_geo = totals.iloc[0]["GEO"]
                if st.button(f"🌍 {top_geo} Sub-Categories →",
                             use_container_width=True, key="ceo_to_subcat"):
                    st.session_state.selected_geo    = top_geo
                    st.session_state.selected_subcat = None
                    st.session_state.view            = "subcategory"
                    st.rerun()


def render_overview():
    st.markdown('<div class="page-title">Amazon P&amp;L Overview</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="page-sub">{d_from.strftime("%d %b %Y")} &rarr; {d_to.strftime("%d %b %Y")} '
        f'&nbsp;&bull;&nbsp; Currency: {"INR (₹)" if use_inr else "Local"} '
        f'&nbsp;&bull;&nbsp; Pace: {days_elapsed}/{_total_days} days elapsed</div>',
        unsafe_allow_html=True)

    where      = build_where()
    where_prev = build_where(date_from=prev_d_from, date_to=prev_d_to)
    where_fm   = build_where(date_from=month_start, date_to=month_end)
    kpi        = get_kpis(where, sfx)
    kpi_prev   = get_kpis(where_prev, sfx)

    if kpi.empty:
        st.warning("📭 No data found for the selected filters. Try widening the date range or clearing some filters.")
        return
    k = kpi.iloc[0]
    kp = kpi_prev.iloc[0] if not kpi_prev.empty else None

    # Pre-fetch GEO breakdown so we can build narrative + movers above KPIs
    df    = get_view1(where, sfx)
    fm_df = get_fm_budget_v1(where_fm, sfx)

    # ── Alert banners (#18) ──
    alerts_html = render_alerts(df, k, agg_label="GEO")
    if alerts_html:
        st.markdown(alerts_html, unsafe_allow_html=True)

    # ── Auto-narrative (#1) ──
    narrative = build_narrative(k, df if not df.empty else None)
    if narrative:
        st.markdown(f'<div class="narrative">📊 {narrative}</div>',
                    unsafe_allow_html=True)

    # ── KPI Cards with period-over-period delta (#2) ──
    def _pop_delta(key_act, mode="ratio"):
        """Return delta vs prior period: ratio = %change, pp = percentage-point diff."""
        if kp is None: return None
        cur, prev = _f(k.get(key_act)), _f(kp.get(key_act))
        if cur is None or prev is None: return None
        if mode == "pp":   return cur - prev
        if prev == 0:      return None
        return (cur - prev) / abs(prev) * 100

    pop_label = (f"vs prior {_period_len}d "
                 f"({prev_d_from.strftime('%d %b')}–{prev_d_to.strftime('%d %b')})")

    cols = st.columns(5)
    cards = [
        ("Revenue vs Budget", "REV_BUDGET", fmt_lakhs(k["SALES_ACT"]), f"Bud: {fmt_lakhs(k['SALES_BUD'])}", k["REV_PCT"],
         kpi_delta(k["REV_DELTA"]),     _pop_delta("SALES_ACT")),
        ("CM1% vs Budget", "CM1", fmt_pct(k["CM1_ACT"]),    f"Bud: {fmt_pct(k['CM1_BUD'])}",     None,
         kpi_delta(k["CM1_DELTA"], unit="pp"),     _pop_delta("CM1_ACT", "pp")),
        ("ACoS%", "ACOS",              fmt_pct(k["ACOS_ACT"]),   f"Bud: {fmt_pct(k['ACOS_BUD'])}",    None,
         kpi_delta(k["ACOS_DELTA"], unit="pp", invert=True), _pop_delta("ACOS_ACT", "pp")),
        ("CM2%", "CM2",               fmt_pct(k["CM2_ACT"]),    f"Bud: {fmt_pct(k['CM2_BUD'])}",     None,
         kpi_delta(k["CM2_DELTA"], unit="pp"),     _pop_delta("CM2_ACT", "pp")),
        ("CM2 Absolute", "CM2_ABS",       fmt_lakhs(k["CM2_ABS_ACT"]), f"Bud: {fmt_lakhs(k['CM2_ABS_BUD'])}", None,
         kpi_delta(k["CM2_ABS_DELTA"]), _pop_delta("CM2_ABS_ACT")),
    ]
    for col, (label, def_key, actual, budget, pct, delta, pop) in zip(cols, cards):
        badge = pct_badge(pct) if pct is not None else ""
        pop_html = ""
        if pop is not None:
            cls = "delta-up" if pop >= 0 else "delta-dn"
            arrow = "▲" if pop >= 0 else "▼"
            unit  = "pp" if "%" in label or label == "ACoS%" else "%"
            pop_html = (f'<div style="font-size:10.5px;color:#7a6a50;'
                        f'margin-top:3px;border-top:1px dashed #d6ccba;padding-top:4px;">'
                        f'<span class="{cls}">{arrow} {abs(pop):.1f}{unit}</span> '
                        f'<span class="small-muted">vs prev period</span></div>')
        tip = METRIC_DEFS.get(def_key, "")
        label_html = (f'<div class="kpi-label" data-tip="{tip}">{label} ⓘ</div>'
                      if tip else f'<div class="kpi-label">{label}</div>')
        inner = "".join([
            label_html,
            f'<div class="kpi-actual">{actual}</div>',
            f'<div class="kpi-budget">{budget}</div>',
            delta or "",
            badge or "",
            pop_html or "",
        ])
        col.markdown(f'<div class="kpi-card">{inner}</div>',
                     unsafe_allow_html=True)
    st.caption(f"📅 Period comparison: prior {_period_len} days ({prev_d_from.strftime('%d %b %Y')} – "
               f"{prev_d_to.strftime('%d %b %Y')})")

    st.markdown('<div class="section-hdr">GEO &times; Channel Breakdown</div>', unsafe_allow_html=True)
    st.caption(f"Pro-rata pace: {days_elapsed} of {_total_days} days elapsed this month  "
               f"|  💡 Click a **GEO TOTAL** row to drill into sub-categories")

    # ── Top movers chips (#6) ──
    movers_html = top_movers_chips(df)
    if movers_html:
        st.markdown(movers_html, unsafe_allow_html=True)

    if df.empty:
        st.info("📭 No data available for the current selection.")
        return

    # ── Variance attribution chart (#20) ──
    with st.expander("📐 Variance attribution by Country", expanded=False):
        st.caption("Each bar shows the contribution of one country to the overall "
                   "sales variance vs budget. Sum of all bars ≈ total variance.")
        vfig = build_variance_chart(df)
        if vfig is not None:
            st.plotly_chart(vfig, use_container_width=True,
                            config={"displayModeBar": False})
        else:
            st.info("Not enough data to compute variance attribution.")

    df = df.merge(fm_df[["GEO","CHANNEL","FM_SALES_BUD","FM_CM2_BUD"]],
                  on=["GEO","CHANNEL"], how="left")

    disp = df.copy()
    disp["CHANNEL"]      = disp["CHANNEL"].astype(str).str.replace("_", " ", regex=False)
    disp["Qty"]          = disp["QTY"].apply(lambda x: f"{x:,.0f}" if pd.notna(x) else "—")
    disp["Revenue Act"]  = disp["SALES_ACT"].apply(fmt_lakhs)
    disp["Revenue Bud"]  = disp["SALES_BUD"].apply(fmt_lakhs)
    disp["CM1% Act"]     = disp["CM1_PCT_ACT"].apply(fmt_pct)
    disp["CM1% Bud"]     = disp["CM1_PCT_BUD"].apply(fmt_pct)
    disp["ACoS% Act"]    = disp["ACOS_ACT"].apply(fmt_pct)
    disp["ACoS% Bud"]    = disp["ACOS_BUD"].apply(fmt_pct)
    disp["CM2% Act"]     = disp["CM2_PCT_ACT"].apply(fmt_pct)
    disp["CM2% Bud"]     = disp["CM2_PCT_BUD"].apply(fmt_pct)
    disp["CM2 Abs Act"]  = disp["CM2_ABS_ACT"].apply(fmt_lakhs)
    disp["CM2 Abs Bud"]  = disp["CM2_ABS_BUD"].apply(fmt_lakhs)
    disp["Rev % Achvd"]  = disp["REV_PCT"].apply(fmt_pct)
    disp["CM2 Abs %"]    = disp["CM2_ABS_ACHVD_PCT"].apply(fmt_pct)
    disp["CM2 Var"]      = disp["CM2_VAR"].apply(
        lambda x: fmt_lakhs(x, signed=True))
    disp["Rev vs Plan"]  = disp.apply(
        lambda r: prorata_str(r["SALES_ACT"], r["FM_SALES_BUD"]), axis=1)

    _rev_pct_n   = pd.to_numeric(df["REV_PCT"],           errors="coerce").reset_index(drop=True)
    _cm2abs_n    = pd.to_numeric(df["CM2_ABS_ACHVD_PCT"],  errors="coerce").reset_index(drop=True)
    _cm2var_n    = pd.to_numeric(df["CM2_VAR"],            errors="coerce").reset_index(drop=True)
    _prorata_s   = disp["Rev vs Plan"].reset_index(drop=True)

    # ── Sparkline data per (GEO, CHANNEL) ── (#3)
    spark_df = get_view1_spark(where, sfx)
    spark_map = {}
    if not spark_df.empty:
        spark_df["DAY"] = pd.to_datetime(spark_df["DAY"])
        spark_df = spark_df.sort_values("DAY")
        for (g, c), grp in spark_df.groupby(["GEO", "CHANNEL"]):
            spark_map[(g, c.replace("_", " "))] = grp["SALES_ACT"].fillna(0).tolist()
        # TOTAL row per GEO = sum across channels by day
        for g, grp in spark_df.groupby("GEO"):
            daily = grp.groupby("DAY")["SALES_ACT"].sum().fillna(0).tolist()
            spark_map[(g, "TOTAL")] = daily

    def _trend(row):
        return spark_map.get((row["GEO"], row["CHANNEL"]), [])
    disp["Trend"] = disp.apply(_trend, axis=1)

    dcols = ["GEO","CHANNEL","Qty","Trend","Revenue Act","Revenue Bud","Rev % Achvd","Rev vs Plan",
             "CM1% Act","CM1% Bud","ACoS% Act","ACoS% Bud",
             "CM2% Act","CM2% Bud","CM2 Abs Act","CM2 Abs Bud","CM2 Abs %","CM2 Var"]

    table_df = disp[dcols].reset_index(drop=True)

    def style_v1(row):
        s = [""] * len(row)
        idx = row.index.tolist()
        s[idx.index("Rev % Achvd")] = color_pct(_rev_pct_n.iloc[row.name])
        s[idx.index("CM2 Abs %")]   = color_pct(_cm2abs_n.iloc[row.name])
        s[idx.index("CM2 Var")]     = color_var(_cm2var_n.iloc[row.name])
        s[idx.index("Rev vs Plan")] = color_prorata(_prorata_s.iloc[row.name])
        if row["CHANNEL"] == "TOTAL":
            s = [(x + TOTAL_ROW).lstrip(";") for x in s]
        return s

    event = st.dataframe(
        table_df.style.apply(style_v1, axis=1).hide(axis="index"),
        use_container_width=True, height=680,
        on_select="rerun", selection_mode="single-row",
        key="overview_table",
        column_config={
            "Trend": st.column_config.LineChartColumn(
                "Daily Sales", width="small",
                help="Daily Sales actual across the period")
        })

    if event.selection.rows:
        idx = event.selection.rows[0]
        row_sel = table_df.iloc[idx]
        if row_sel["CHANNEL"] == "TOTAL":
            st.session_state.selected_geo    = row_sel["GEO"]
            st.session_state.selected_subcat = None
            st.session_state.view            = "subcategory"
            st.rerun()
        else:
            st.caption(f"ℹ️ Selected {row_sel['GEO']} / {row_sel['CHANNEL']}. "
                       "Click a **GEO TOTAL** row to drill into sub-categories.")


# ═══════════════════════════════════════════════════════════════════════════════
# VIEW 2 — Sub-Category Breakdown
# ═══════════════════════════════════════════════════════════════════════════════
def render_subcategory():
    geo = st.session_state.selected_geo

    c1, c2 = st.columns([1, 9])
    with c1:
        if st.button("← Back"):
            st.session_state.view = "overview"
            st.rerun()
    with c2:
        render_breadcrumbs([
            ("Overview", "overview", None, None),
            (geo, "subcategory", geo, None),
        ])
        st.markdown(
            f'<div class="page-title">Sub-Category Breakdown &mdash; {geo}</div>',
            unsafe_allow_html=True)
        st.markdown(
            f'<div class="page-sub">{d_from.strftime("%d %b %Y")} &rarr; {d_to.strftime("%d %b %Y")} '
            f'&nbsp;&bull;&nbsp; Currency: {"INR (₹)" if use_inr else "Local"} '
            f'&nbsp;&bull;&nbsp; Pace: {days_elapsed}/{_total_days} days</div>',
            unsafe_allow_html=True)

    where    = build_where(geo_override=geo)
    where_fm = build_where(geo_override=geo, date_from=month_start, date_to=month_end)
    df       = get_view2(where, sfx)
    fm_df    = get_fm_budget_v2(where_fm, sfx)

    if df.empty:
        st.warning("📭 No sub-category data found for this selection.")
        return

    df = df.merge(fm_df[["SUB_CATEGORY","FM_SALES_BUD"]], on="SUB_CATEGORY", how="left")

    # ── Mini KPIs ──
    tot = df[df["SUB_CATEGORY"] == "GRAND TOTAL"]
    if not tot.empty:
        t = tot.iloc[0]
        fm_bud = _f(t.get("FM_SALES_BUD"))
        rev_vs_plan = (prorata_str(t["SALES_ACT"], fm_bud)
                       if fm_bud else fmt_pct(t["REV_PCT"]))
        cards = [
            ("Revenue Actual", fmt_lakhs(t["SALES_ACT"]),     f"Bud: {fmt_lakhs(t['SALES_BUD'])}"),
            ("Rev vs Plan",    rev_vs_plan,                    f"Achvd: {fmt_pct(t['REV_PCT'])}"),
            ("CM1 Actual",     fmt_lakhs(t["CM1_ACT"]),        f"Bud: {fmt_lakhs(t['CM1_BUD'])}"),
            ("CM2 Actual",     fmt_lakhs(t["CM2_ACT"]),        f"Bud: {fmt_lakhs(t['CM2_BUD'])}"),
            ("CM2 % Achieved", fmt_pct(t["CM2_ABS_ACHVD_PCT"]), None),
        ]
        cols = st.columns(5)
        for col, (lbl, val, sub) in zip(cols, cards):
            col.markdown(strip_card(lbl, val, sub), unsafe_allow_html=True)
        st.markdown("")

    st.markdown('<div class="section-hdr">Sub-Category P&amp;L · '
                '<span style="font-size:12px;color:#7a6a50;font-weight:500;">'
                'click a row to drill into ASINs</span></div>', unsafe_allow_html=True)

    disp = df.copy()
    disp["Budget Rev"]   = disp["SALES_BUD"].apply(fmt_lakhs)
    disp["Actual Rev"]   = disp["SALES_ACT"].apply(fmt_lakhs)
    disp["Budget CM1"]   = disp["CM1_BUD"].apply(fmt_lakhs)
    disp["Actual CM1"]   = disp["CM1_ACT"].apply(fmt_lakhs)
    disp["Budget CM2"]   = disp["CM2_BUD"].apply(fmt_lakhs)
    disp["Actual CM2"]   = disp["CM2_ACT"].apply(fmt_lakhs)
    disp["% Achieved"]   = disp["REV_PCT"].apply(fmt_pct)
    disp["CM2 Abs %"]    = disp["CM2_ABS_ACHVD_PCT"].apply(fmt_pct)
    disp["CM2 Var"]      = disp["CM2_VAR"].apply(
        lambda x: fmt_lakhs(x, signed=True))
    disp["Rev vs Plan"]  = disp.apply(
        lambda r: prorata_str(r["SALES_ACT"], r["FM_SALES_BUD"]), axis=1)

    _rev_n2  = pd.to_numeric(df["REV_PCT"],          errors="coerce").reset_index(drop=True)
    _cm2a_n2 = pd.to_numeric(df["CM2_ABS_ACHVD_PCT"], errors="coerce").reset_index(drop=True)
    _var_n2  = pd.to_numeric(df["CM2_VAR"],           errors="coerce").reset_index(drop=True)
    _pro_s2  = disp["Rev vs Plan"].reset_index(drop=True)

    dcols2 = ["SUB_CATEGORY","Budget Rev","Actual Rev","% Achieved","Rev vs Plan",
              "Budget CM1","Actual CM1","Budget CM2","Actual CM2","CM2 Abs %","CM2 Var"]
    table_df2 = disp[dcols2].rename(columns={"SUB_CATEGORY":"Sub-Category"}).reset_index(drop=True)

    def style_v2(row):
        s = [""] * len(row)
        idx = row.index.tolist()
        s[idx.index("% Achieved")]  = color_pct(_rev_n2.iloc[row.name])
        s[idx.index("CM2 Abs %")]   = color_pct(_cm2a_n2.iloc[row.name])
        s[idx.index("CM2 Var")]     = color_var(_var_n2.iloc[row.name])
        s[idx.index("Rev vs Plan")] = color_prorata(_pro_s2.iloc[row.name])
        if row["Sub-Category"] == "GRAND TOTAL":
            s = [(x + TOTAL_ROW).lstrip(";") for x in s]
        return s

    event = st.dataframe(
        table_df2.style.apply(style_v2, axis=1).hide(axis="index"),
        use_container_width=True, height=550,
        on_select="rerun", selection_mode="single-row",
        key="subcat_table")

    if event.selection.rows:
        idx = event.selection.rows[0]
        clicked = table_df2.iloc[idx]["Sub-Category"]
        if clicked and clicked != "GRAND TOTAL":
            st.session_state.selected_subcat = clicked
            st.session_state.view = "asin"
            st.rerun()
        elif clicked == "GRAND TOTAL":
            st.caption("ℹ️ Click a specific sub-category row to drill into ASINs. "
                       "Grand Total isn't drillable.")


# ═══════════════════════════════════════════════════════════════════════════════
# VIEW 3 — ASIN Level
# ═══════════════════════════════════════════════════════════════════════════════
def render_asin():
    geo     = st.session_state.selected_geo
    subcat  = st.session_state.selected_subcat

    c1, c2 = st.columns([1, 9])
    with c1:
        if st.button("← Back"):
            st.session_state.view = "subcategory"
            st.rerun()
    with c2:
        render_breadcrumbs([
            ("Overview",  "overview",    None, None),
            (geo,         "subcategory", geo,  None),
            (subcat,      "asin",        geo,  subcat),
        ])
        st.markdown(
            f'<div class="page-title">ASIN View &mdash; {geo} / {subcat}</div>',
            unsafe_allow_html=True)
        st.markdown(
            f'<div class="page-sub">{d_from.strftime("%d %b %Y")} &rarr; {d_to.strftime("%d %b %Y")} '
            f'&nbsp;&bull;&nbsp; Currency: {"INR (₹)" if use_inr else "Local"}</div>',
            unsafe_allow_html=True)

    where = build_where(geo_override=geo)
    df    = get_asin_data(where, geo, subcat, sfx)

    if df.empty:
        st.warning("📭 No ASIN data found for this selection. Try a different sub-category or date range.")
        return

    # ── Summary KPIs ──
    act_rev  = _f(df["ACT_REVENUE"].sum())
    bud_rev  = _f(df["BUD_REVENUE"].sum())
    act_cm2  = _f(df["ACT_CM2_ABS"].sum())
    bud_cm2  = _f(df["CM2_BUD"].sum()) if "CM2_BUD" in df.columns else None
    paid_spd = _f(df["PAID_SPEND"].sum())
    paid_rev = _f(df["PAID_REVENUE"].sum())
    impressions = _f(df["IMPRESSIONS"].sum())

    pacos = (paid_rev / paid_spd * 100) if (paid_spd and paid_rev) else None
    cards = [
        ("Total Revenue",  fmt_lakhs(act_rev),  f"Bud: {fmt_lakhs(bud_rev)}"),
        ("CM2 Absolute",   fmt_lakhs(act_cm2),  f"Bud: {fmt_lakhs(bud_cm2)}" if bud_cm2 else None),
        ("Total Ad Spend", fmt_lakhs(paid_spd), None),
        ("Paid Revenue",   fmt_lakhs(paid_rev),
            f"PACoS: {fmt_pct(pacos)}" if pacos else None),
        ("Impressions",
            f"{impressions/1e6:.2f}M" if impressions else "—",
            f"ASINs: {len(df):,}"),
    ]
    cols = st.columns(5)
    for col, (lbl, val, sub) in zip(cols, cards):
        col.markdown(strip_card(lbl, val, sub), unsafe_allow_html=True)
    st.markdown("")

    # ── Brand filter (applies to all 3 tabs) ──
    if "BRAND" in df.columns:
        brand_opts = sorted(b for b in df["BRAND"].dropna().unique() if str(b).strip())
        if len(brand_opts) > 1:
            bf1, bf2 = st.columns([4, 6])
            with bf1:
                picked = st.multiselect(
                    f"🏷️ Filter by Brand ({len(brand_opts)} available)",
                    brand_opts,
                    key=f"asin_brand_{geo}_{subcat}",
                    placeholder="All brands")
            if picked:
                df = df[df["BRAND"].isin(picked)].reset_index(drop=True)
                with bf2:
                    st.markdown(
                        f'<div style="padding-top:32px;font-size:12px;color:#7a6a50;">'
                        f'Showing <b style="color:#004A2B;">{len(df):,}</b> of '
                        f'{len(brand_opts)} brands &nbsp;·&nbsp; '
                        f'<b>{", ".join(picked)}</b></div>',
                        unsafe_allow_html=True)
        if df.empty:
            st.info("📭 No ASINs match the selected brand(s).")
            return

    # ── Tabs ──
    tab_pnl, tab_ads, tab_chart = st.tabs(
        ["📊 P&L vs Budget", "📣 Ad Performance", "🫧 Bubble Chart"])

    # ── Tab 1: P&L ──
    with tab_pnl:
        # ── Cohort toggle (#8) ──
        cc1, cc2, cc3 = st.columns([3, 2, 3])
        with cc1:
            cohort = st.radio("Sort by",
                              ["Revenue (Actual)", "CM2 Margin %", "CM2 Profit (Abs)", "Rev % Achieved"],
                              horizontal=True, key=f"asin_cohort_{geo}_{subcat}")
        with cc2:
            top_n = st.selectbox("Show",
                                 ["All", "Top 10", "Top 20", "Top 50"],
                                 index=0, key=f"asin_topn_{geo}_{subcat}")
        with cc3:
            st.markdown(
                f'<div style="padding-top:32px;font-size:11.5px;color:#7a6a50;">'
                f'<b>{len(df):,}</b> ASINs in {subcat} · {geo}</div>',
                unsafe_allow_html=True)

        sort_key_map = {
            "Revenue (Actual)":   ("ACT_REVENUE",   False),
            "CM2 Margin %":       ("ACT_CM2_PCT",   False),
            "CM2 Profit (Abs)":   ("ACT_CM2_ABS",   False),
            "Rev % Achieved":     ("REV_ACHVD_PCT", False),
        }
        sort_col, asc = sort_key_map[cohort]
        if sort_col in df.columns:
            df = df.sort_values(sort_col, ascending=asc, na_position="last").reset_index(drop=True)
        if top_n != "All":
            n = int(top_n.split()[1])
            df = df.head(n).reset_index(drop=True)

        st.caption(f"Sorted by **{cohort}** · "
                   f"All budget figures from P&L table for the same date range. "
                   f"Actuals = total sales (organic + paid).")
        pnl_cols = [
            ("ASIN",          "ASIN"),
            ("PRODUCT_NAME",  "Product"),
            ("BRAND",         "Brand"),
            ("ACT_UNITS",     "Act Units"),
            ("BUD_UNITS",     "Bud Units"),
            ("ACT_REVENUE",   "Act Rev"),
            ("BUD_REVENUE",   "Bud Rev"),
            ("REV_ACHVD_PCT", "Rev %"),
            ("ACT_ASP",       "Act ASP"),
            ("BUD_ASP",       "Bud ASP"),
            ("ACT_CM1_PCT",   "Act CM1%"),
            ("BUD_CM1_PCT",   "Bud CM1%"),
            ("ACT_ACOS_PCT",  "Act ACoS%"),
            ("BUD_ACOS_PCT",  "Bud ACoS%"),
            ("ACT_CM2_PCT",   "Act CM2%"),
            ("BUD_CM2_PCT",   "Bud CM2%"),
            ("ACT_CM2_ABS",   "CM2 Abs"),
        ]
        p = df[[c for c,_ in pnl_cols]].rename(columns=dict(pnl_cols)).copy()
        p["Act Units"] = p["Act Units"].apply(fmt_num)
        p["Bud Units"] = p["Bud Units"].apply(fmt_num)
        p["Act Rev"]   = df["ACT_REVENUE"].apply(fmt_lakhs)
        p["Bud Rev"]   = df["BUD_REVENUE"].apply(fmt_lakhs)
        p["CM2 Abs"]   = df["ACT_CM2_ABS"].apply(fmt_lakhs)
        p["Act ASP"]   = df["ACT_ASP"].apply(lambda v: fmt_ccy(v))
        p["Bud ASP"]   = df["BUD_ASP"].apply(lambda v: fmt_ccy(v))
        for col in ["Rev %","Act CM1%","Bud CM1%","Act ACoS%","Bud ACoS%","Act CM2%","Bud CM2%"]:
            src = [c for c,n in pnl_cols if n == col][0]
            p[col] = df[src].apply(fmt_pct)

        _rev_achvd   = pd.to_numeric(df["REV_ACHVD_PCT"], errors="coerce").reset_index(drop=True)
        _acos_delta  = (pd.to_numeric(df["ACT_ACOS_PCT"], errors="coerce") -
                        pd.to_numeric(df["BUD_ACOS_PCT"], errors="coerce")).reset_index(drop=True)
        _cm2_delta   = (pd.to_numeric(df["ACT_CM2_PCT"], errors="coerce") -
                        pd.to_numeric(df["BUD_CM2_PCT"], errors="coerce")).reset_index(drop=True)

        p = p.reset_index(drop=True)

        def style_pnl(row):
            s = [""] * len(row)
            idx = row.index.tolist()
            if "Rev %" in idx:
                s[idx.index("Rev %")]     = color_pct(_rev_achvd.iloc[row.name])
            if "Act ACoS%" in idx:
                v = _f(_acos_delta.iloc[row.name])
                if v is not None:
                    s[idx.index("Act ACoS%")] = ("color:#8b1a1a;font-weight:600" if v > 0
                                                  else "color:#004A2B;font-weight:600")
            if "Act CM2%" in idx:
                v = _f(_cm2_delta.iloc[row.name])
                if v is not None:
                    s[idx.index("Act CM2%")] = ("color:#004A2B;font-weight:600" if v > 0
                                                 else "color:#8b1a1a;font-weight:600")
            return s

        st.dataframe(
            p.style.apply(style_pnl, axis=1).hide(axis="index"),
            use_container_width=True, height=500)

    # ── Tab 2: Ad Performance ──
    with tab_ads:
        st.caption("Paid ad metrics from marketing table. PACoS = Paid Revenue / Spend (higher = better). CTR, Conv Rate in %.")
        ads_cols = [
            ("ASIN",          "ASIN"),
            ("PRODUCT_NAME",  "Product"),
            ("PAID_SPEND",    "Spend"),
            ("PAID_REVENUE",  "Paid Rev"),
            ("PAID_UNITS",    "Paid Units"),
            ("IMPRESSIONS",   "Impressions"),
            ("CLICKS",        "Clicks"),
            ("CTR_PCT",       "CTR%"),
            ("CPC",           "CPC"),
            ("AD_ACOS_PCT",   "ACoS%"),
            ("PACOS",         "PACoS"),
            ("CONV_RATE_PCT", "Conv%"),
            ("PCT_PAID_SALES","Paid%"),
        ]
        a = df[[c for c,_ in ads_cols]].rename(columns=dict(ads_cols)).copy()
        a["Spend"]       = df["PAID_SPEND"].apply(fmt_lakhs)
        a["Paid Rev"]    = df["PAID_REVENUE"].apply(fmt_lakhs)
        a["Paid Units"]  = df["PAID_UNITS"].apply(fmt_num)
        a["Impressions"] = df["IMPRESSIONS"].apply(lambda v: fmt_num(v, 0))
        a["Clicks"]      = df["CLICKS"].apply(fmt_num)
        a["CTR%"]        = df["CTR_PCT"].apply(fmt_pct)
        a["CPC"]         = df["CPC"].apply(lambda v: fmt_ccy(v))
        a["ACoS%"]       = df["AD_ACOS_PCT"].apply(fmt_pct)
        a["PACoS"]       = df["PACOS"].apply(lambda v: f"{_f(v):.2f}×" if _f(v) else "—")
        a["Conv%"]       = df["CONV_RATE_PCT"].apply(fmt_pct)
        a["Paid%"]       = df["PCT_PAID_SALES"].apply(fmt_pct)

        _acos_ad  = pd.to_numeric(df["AD_ACOS_PCT"], errors="coerce").reset_index(drop=True)
        _pacos_n  = pd.to_numeric(df["PACOS"],       errors="coerce").reset_index(drop=True)
        a = a.reset_index(drop=True)

        def style_ads(row):
            s = [""] * len(row)
            idx = row.index.tolist()
            if "ACoS%" in idx:
                v = _f(_acos_ad.iloc[row.name])
                if v is not None:
                    s[idx.index("ACoS%")] = (
                        "background-color:#d6ece1;color:#004A2B;font-weight:600" if v <= 20 else
                        "background-color:#fef3d6;color:#7a5c00;font-weight:600" if v <= 35 else
                        "background-color:#fde8e8;color:#8b1a1a;font-weight:600")
            if "PACoS" in idx:
                v = _f(_pacos_n.iloc[row.name])
                if v is not None:
                    s[idx.index("PACoS")] = (
                        "color:#004A2B;font-weight:600" if v >= 3 else
                        "color:#7a5c00;font-weight:600" if v >= 1.5 else
                        "color:#8b1a1a;font-weight:600")
            return s

        st.dataframe(
            a.style.apply(style_ads, axis=1).hide(axis="index"),
            use_container_width=True, height=500)

    # ── Tab 3: Bubble Chart ──
    with tab_chart:
        if not HAS_PLOTLY:
            st.info("Install plotly (`pip install plotly`) to see the interactive chart.")
        else:
            chart_df = df[df["IMPRESSIONS"] > 0].copy()
            if chart_df.empty:
                st.info("No ad impressions data available for charting.")
            else:
                chart_df["_spend_size"] = pd.to_numeric(chart_df["PAID_SPEND"], errors="coerce").fillna(0).clip(lower=1)
                chart_df["_cm2"]        = pd.to_numeric(chart_df["ACT_CM2_PCT"], errors="coerce")
                chart_df["_acos"]       = pd.to_numeric(chart_df["AD_ACOS_PCT"], errors="coerce")
                chart_df["_impr"]       = pd.to_numeric(chart_df["IMPRESSIONS"], errors="coerce")
                chart_df["_rev"]        = pd.to_numeric(chart_df["ACT_REVENUE"], errors="coerce")
                chart_df["_name_short"] = chart_df["PRODUCT_NAME"].str[:40]
                chart_df["_rev_fmt"]    = chart_df["ACT_REVENUE"].apply(fmt_lakhs)
                chart_df["_spend_fmt"]  = chart_df["PAID_SPEND"].apply(fmt_lakhs)
                chart_df["_ctr_fmt"]    = chart_df["CTR_PCT"].apply(fmt_pct)
                chart_df["_conv_fmt"]   = chart_df["CONV_RATE_PCT"].apply(fmt_pct)
                chart_df["_paid_pct"]   = chart_df["PCT_PAID_SALES"].apply(fmt_pct)
                chart_df["_bud_rev_fmt"]= chart_df["BUD_REVENUE"].apply(fmt_lakhs)
                chart_df["_rev_achvd"]  = chart_df["REV_ACHVD_PCT"].apply(fmt_pct)

                # Strong diverging color scale: red (loss) → amber (thin) → green (healthy)
                _cm2_vals = chart_df["_cm2"].dropna()
                _cm2_min = float(_cm2_vals.min()) if not _cm2_vals.empty else -10.0
                _cm2_max = float(_cm2_vals.max()) if not _cm2_vals.empty else 40.0
                # Anchor 0% at the neutral point of the scale when range spans negative→positive
                color_scale = [
                    [0.00, "#8b1a1a"],   # deep red
                    [0.25, "#d35a4a"],   # red-orange
                    [0.50, "#e8b94d"],   # amber/gold
                    [0.75, "#6db86b"],   # mid green
                    [1.00, "#1a7a3e"],   # deep green
                ]
                fig = px.scatter(
                    chart_df.dropna(subset=["_acos","_impr"]),
                    x="_impr",
                    y="_acos",
                    size="_spend_size",
                    color="_cm2",
                    color_continuous_scale=color_scale,
                    range_color=[_cm2_min, _cm2_max],
                    hover_name="_name_short",
                    custom_data=["ASIN","_rev_fmt","_bud_rev_fmt","_rev_achvd",
                                 "_spend_fmt","_ctr_fmt","_conv_fmt","_paid_pct",
                                 "ACT_UNITS","ACT_CM1_PCT","ACT_CM2_PCT","BUD_CM2_PCT"],
                    size_max=58,
                    labels={"_impr":"Impressions","_acos":"ACoS%","_cm2":"CM2%"},
                    title=f"ASIN Performance — {geo} / {subcat}  |  Bubble size = Ad Spend  |  Color = CM2%"
                )
                fig.update_traces(
                    marker=dict(
                        opacity=0.85,
                        line=dict(width=1.5, color="rgba(0,74,43,0.55)"),
                        sizemin=8,
                    ),
                    hovertemplate=(
                        "<b>%{hovertext}</b><br>"
                        "ASIN: %{customdata[0]}<br>"
                        "──────────────────<br>"
                        "Total Revenue: %{customdata[1]}  (Bud: %{customdata[2]})<br>"
                        "Rev % Achieved: %{customdata[3]}<br>"
                        "Units: %{customdata[8]}<br>"
                        "──────────────────<br>"
                        "Ad Spend: %{customdata[4]}<br>"
                        "Impressions: %{x:,.0f}<br>"
                        "ACoS: %{y:.1f}%<br>"
                        "CTR: %{customdata[5]}  |  Conv Rate: %{customdata[6]}<br>"
                        "% Paid Sales: %{customdata[7]}<br>"
                        "──────────────────<br>"
                        "CM1%: %{customdata[9]:.1f}%  |  CM2%: %{customdata[10]:.1f}%  (Bud: %{customdata[11]:.1f}%)<br>"
                        "<extra></extra>"
                    )
                )
                fig.update_layout(
                    plot_bgcolor="#FBF5EA",
                    paper_bgcolor="#FBF5EA",
                    font=dict(family="Proxima Nova, Arial", color="#171717"),
                    coloraxis_colorbar=dict(title="CM2%", ticksuffix="%",
                                            thickness=14, len=0.75,
                                            bgcolor="rgba(255,255,255,0.4)",
                                            outlinewidth=0),
                    xaxis_title="Impressions",
                    yaxis_title="ACoS%",
                    height=540,
                    margin=dict(l=40, r=40, t=60, b=40),
                    hoverlabel=dict(bgcolor="#ffffff", font=dict(color="#171717")),
                )
                fig.update_xaxes(gridcolor="rgba(171,135,67,0.18)", zerolinecolor="rgba(171,135,67,0.3)")
                fig.update_yaxes(gridcolor="rgba(171,135,67,0.18)", zerolinecolor="rgba(171,135,67,0.3)")
                fig.add_hline(y=20, line_dash="dash", line_color="#1a7a3e", line_width=2,
                              opacity=0.65,
                              annotation_text="ACoS 20% (efficient)",
                              annotation_position="right",
                              annotation_font=dict(size=10.5, color="#1a7a3e"))
                fig.add_hline(y=35, line_dash="dash", line_color="#8b1a1a", line_width=2,
                              opacity=0.65,
                              annotation_text="ACoS 35% (unhealthy)",
                              annotation_position="right",
                              annotation_font=dict(size=10.5, color="#8b1a1a"))
                st.plotly_chart(fig, use_container_width=True,
                                config={"displayModeBar": False})
                st.caption("**Bubble colour** = CM2% margin (red = unprofitable, green = healthy). "
                           "**Bubble size** = Ad Spend. **Y-axis ACoS%**: under 20% is efficient, "
                           "20–35% acceptable, above 35% is unhealthy.")


# ═══════════════════════════════════════════════════════════════════════════════
# VIEW 4 — P&L Statement
# ═══════════════════════════════════════════════════════════════════════════════
def render_pnl():
    c1, c2 = st.columns([1, 9])
    with c1:
        if st.button("← Back", key="pnl_back"):
            st.session_state.view = "overview"
            st.rerun()
    with c2:
        st.markdown('<div class="page-title">P&amp;L Statement</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="page-sub">{d_from.strftime("%d %b %Y")} &rarr; {d_to.strftime("%d %b %Y")}'
            f' &nbsp;&bull;&nbsp; Currency: {"INR (₹)" if use_inr else "Local"}'
            f' &nbsp;&bull;&nbsp; {(d_to - d_from).days + 1} days</div>',
            unsafe_allow_html=True)
        if sku_search and sku_search.strip():
            st.markdown(
                f'<div style="display:inline-block;background:#fef3d6;color:#7a5c00;'
                f'padding:4px 12px;border-radius:14px;font-size:12px;font-weight:600;'
                f'margin:4px 0 12px 0;">🔍 Filtered by: <b>{sku_search.strip()}</b></div>',
                unsafe_allow_html=True)

    where = build_where()

    # ── Summary KPI strip ──
    with st.spinner("Loading summary…"):
        _agg = get_pnl_agg(where, sfx)

    if not _agg.empty:
        _r = {k.upper(): v for k, v in _agg.iloc[0].items()}
        def _safe(a, b):
            an, bn = _f(a), _f(b)
            if an is None or bn is None or bn == 0: return None
            return (an / bn) * 100

        sales_act = _f(_r.get("SALES_ACT"))
        cm1_act   = _f(_r.get("CM1_ACT"))
        cm2_act   = _f(_r.get("CM2_ACT"))
        pm_act    = _f(_r.get("PM_SPEND_ACT"))
        cm1_pct   = _safe(cm1_act, sales_act)
        cm2_pct   = _safe(cm2_act, sales_act)
        rev_pct   = _safe(sales_act, _f(_r.get("SALES_BUD")))

        def _strip_card(label, val, sub):
            return (f'<div class="pnl-strip">'
                    f'<div class="pnl-strip-label">{label}</div>'
                    f'<div class="pnl-strip-val">{val}</div>'
                    f'<div class="pnl-strip-sub">{sub}</div></div>')

        scols = st.columns(5)
        scols[0].markdown(_strip_card("Sales", fmt_lakhs(sales_act),
            f"Bud: {fmt_lakhs(_r.get('SALES_BUD'))}"), unsafe_allow_html=True)
        scols[1].markdown(_strip_card("CM1 Margin", fmt_pct(cm1_pct),
            f"Abs: {fmt_lakhs(cm1_act)}"), unsafe_allow_html=True)
        scols[2].markdown(_strip_card("CM2 Margin", fmt_pct(cm2_pct),
            f"Abs: {fmt_lakhs(cm2_act)}"), unsafe_allow_html=True)
        scols[3].markdown(_strip_card("PM Spend", fmt_lakhs(pm_act),
            f"Bud: {fmt_lakhs(_r.get('PM_SPEND_BUD'))}"), unsafe_allow_html=True)
        scols[4].markdown(_strip_card("Rev vs Bud", fmt_pct(rev_pct),
            f"Δ: {fmt_lakhs((sales_act or 0) - (_f(_r.get('SALES_BUD')) or 0))}"),
            unsafe_allow_html=True)
        st.markdown("")

    t1, t2, t3, t4, t5 = st.tabs([
        "📊 P&L Statement", "📈 Daily Trend",
        "🗂️ By Category", "🛒 By Channel", "🌍 By Country",
    ])

    # ── Tab 1: Waterfall ──
    with t1:
        if _agg.empty:
            st.warning("📭 No data found for selected filters. Try adjusting the date range or filters.")
        else:
            row = {k.upper(): v for k, v in _agg.iloc[0].items()}
            wf  = _build_waterfall(row)
            wf_df = pd.DataFrame([{k: v for k, v in r.items() if not k.startswith("_")}
                                   for r in wf]).reset_index(drop=True)
            _types = [r["_type"] for r in wf]
            _vars  = [r["_var"]  for r in wf]
            _costs = [r["_cost"] for r in wf]

            def style_wf(row):
                s   = [""] * len(row)
                idx = row.index.tolist()
                rt  = _types[row.name]
                var = _vars[row.name]
                ic  = _costs[row.name]
                for vcol in ["Variance (INR)", "Var %"]:
                    if vcol in idx and var is not None:
                        bad = (var > 0 and ic) or (var < 0 and not ic)
                        s[idx.index(vcol)] = ("color:#8b1a1a;font-weight:600" if bad
                                              else "color:#004A2B;font-weight:600")
                if rt == "total":
                    s = [(x + ";font-weight:700;background:#c8e6d4;color:#004A2B"
                          ";font-size:13px").lstrip(";") for x in s]
                elif rt == "subtotal":
                    s = [(x + ";font-weight:700;background:#EDE8DC;color:#004A2B").lstrip(";")
                         for x in s]
                return s

            st.dataframe(
                wf_df.style.apply(style_wf, axis=1).hide(axis="index"),
                use_container_width=True, height=490)
            ec1, ec2 = st.columns([6, 1])
            with ec1:
                st.caption("Variance = Actual − Budget. "
                           "For cost lines: green = under budget (good). "
                           "For revenue/CM lines: green = above budget (good). "
                           "— means column not available in source table.")
            with ec2:
                st.download_button("📥 CSV", wf_df.to_csv(index=False).encode("utf-8"),
                    file_name=f"pnl_statement_{d_from}_{d_to}.csv",
                    mime="text/csv", use_container_width=True, key="dl_pnl")

    # ── Tab 2: Daily Trend ──
    with t2:
        with st.spinner("Loading daily trend…"):
            daily = get_pnl_daily(where, sfx)
        if daily.empty:
            st.info("📭 No daily data available.")
        else:
            if HAS_PLOTLY:
                daily["DAY"] = pd.to_datetime(daily["DAY"])
                fig = go.Figure()
                trace_cfgs = [
                    ("SALES_ACT",    "Sales (Actual)",   "#004A2B", "solid"),
                    ("SALES_BUD",    "Sales (Budget)",   "#004A2B", "dot"),
                    ("CM1_ACT",      "CM1 (Actual)",     "#AB8743", "solid"),
                    ("CM2_ACT",      "CM2 (Actual)",     "#2E7D32", "solid"),
                    ("PM_SPEND_ACT", "PM Spend (Actual)","#8b1a1a", "dash"),
                ]
                # Pick axis unit based on peak magnitude across all traces
                _peak = 0.0
                for col, *_ in trace_cfgs:
                    if col in daily.columns:
                        _peak = max(_peak, pd.to_numeric(daily[col],
                                    errors="coerce").abs().max() or 0)
                if _peak >= 1e7:
                    _div, _unit = 1e7, "Cr"
                elif _peak >= 1e5:
                    _div, _unit = 1e5, "L"
                elif _peak >= 1e3:
                    _div, _unit = 1e3, "K"
                else:
                    _div, _unit = 1, ""

                for col, name, color, dash in trace_cfgs:
                    if col in daily.columns:
                        y = pd.to_numeric(daily[col], errors="coerce") / _div
                        fig.add_trace(go.Scatter(
                            x=daily["DAY"], y=y, mode="lines+markers", name=name,
                            line=dict(color=color, dash=dash, width=2.5),
                            marker=dict(size=5),
                            hovertemplate=(f"<b>{name}</b><br>%{{x|%d %b}}<br>"
                                           f"{sym}%{{y:.2f}}{_unit}<extra></extra>"),
                        ))
                _title_unit = f" (₹ {_unit})" if _unit else ""
                fig.update_layout(
                    title=dict(text=f"<b>Daily P&L Trend</b>{_title_unit}",
                               font=dict(size=16, color="#004A2B")),
                    plot_bgcolor="#FBF5EA", paper_bgcolor="#FBF5EA",
                    font=dict(family="Arial", color="#171717"),
                    height=440, margin=dict(l=40, r=40, t=60, b=60),
                    legend=dict(orientation="h", yanchor="bottom", y=-0.4,
                                bgcolor="rgba(0,0,0,0)"),
                    hovermode="x unified",
                )
                fig.update_xaxes(title_text="Date", showgrid=True, gridcolor="rgba(171,135,67,0.15)")
                fig.update_yaxes(title_text=f"₹ {_unit}".strip(),
                                  showgrid=True, gridcolor="rgba(171,135,67,0.15)")
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
            else:
                st.info("Install plotly for the chart view.")

            # Daily table
            dt = daily.copy()
            dt["Date"] = pd.to_datetime(dt["DAY"]).dt.strftime("%d %b")
            col_map = [("SALES_ACT","Sales Act"), ("SALES_BUD","Sales Bud"),
                       ("CM1_ACT","CM1 Act"), ("CM2_ACT","CM2 Act"),
                       ("PM_SPEND_ACT","PM Spend")]
            for src, lbl in col_map:
                if src in dt.columns:
                    dt[lbl] = dt[src].apply(fmt_lakhs)
            show = ["Date"] + [lbl for src, lbl in col_map if src in dt.columns]
            daily_disp = dt[show].reset_index(drop=True)
            st.dataframe(daily_disp, use_container_width=True, height=320)
            _dl1, _dl2 = st.columns([6, 1])
            with _dl2:
                st.download_button("📥 CSV", daily_disp.to_csv(index=False).encode("utf-8"),
                    file_name=f"pnl_daily_{d_from}_{d_to}.csv",
                    mime="text/csv", use_container_width=True, key="dl_pnl_daily")

    def _render_breakdown(df_in, dim_col, dim_label, section_hdr, dl_key, file_slug):
        """Render a P&L breakdown table with %-of-total, Rev %, totals row, and CSV export."""
        if df_in.empty:
            st.info(f"📭 No {dim_label.lower()} data available.")
            return
        disp = df_in.copy()
        col_map = [("SALES_ACT","Sales Act"), ("SALES_BUD","Sales Bud"),
                   ("CM1_ACT","CM1 Act"), ("CM2_ACT","CM2 Act"),
                   ("PM_SPEND_ACT","PM Spend")]
        for src, lbl in col_map:
            if src in disp.columns:
                disp[lbl] = disp[src].apply(fmt_lakhs)

        _of_total_n = None
        if "SALES_ACT" in disp.columns:
            _sales_num = pd.to_numeric(disp["SALES_ACT"], errors="coerce")
            _gt_mask   = disp[dim_col] == "GRAND TOTAL"
            _gt_val    = _sales_num[_gt_mask].iloc[0] if _gt_mask.any() else _sales_num.sum()
            _of_total_n = (_sales_num / _gt_val * 100).reset_index(drop=True)
            disp["% of Total"] = _of_total_n.apply(fmt_pct)

        _rev_n = None
        if "SALES_ACT" in disp.columns and "SALES_BUD" in disp.columns:
            _rev_n = (pd.to_numeric(disp["SALES_ACT"], errors="coerce") /
                      pd.to_numeric(disp["SALES_BUD"], errors="coerce") * 100
                     ).reset_index(drop=True)
            disp["Rev %"] = _rev_n.apply(fmt_pct)

        labels  = [lbl for src, lbl in col_map if src in disp.columns]
        show_c  = [dim_col] + labels
        if "% of Total" in disp.columns: show_c.append("% of Total")
        if "Rev %"      in disp.columns: show_c.append("Rev %")
        ct      = disp[show_c].rename(columns={dim_col: dim_label}).reset_index(drop=True)

        def style_row(row):
            s   = [""] * len(row)
            idx = row.index.tolist()
            if "Rev %" in idx and _rev_n is not None:
                s[idx.index("Rev %")] = color_pct(_rev_n.iloc[row.name])
            if row.get(dim_label) == "GRAND TOTAL":
                s = [(x + TOTAL_ROW).lstrip(";") for x in s]
            return s

        st.markdown(f'<div class="section-hdr">{section_hdr}</div>',
                    unsafe_allow_html=True)
        st.dataframe(ct.style.apply(style_row, axis=1).hide(axis="index"),
                     use_container_width=True, height=420)
        _cl1, _cl2 = st.columns([6, 1])
        with _cl1:
            st.caption("**% of Total** = share of Grand Total Sales (Actual). "
                       "**Rev %** = Sales Actual ÷ Sales Budget.")
        with _cl2:
            st.download_button("📥 CSV", ct.to_csv(index=False).encode("utf-8"),
                file_name=f"pnl_{file_slug}_{d_from}_{d_to}.csv",
                mime="text/csv", use_container_width=True, key=dl_key)

    # ── Tab 3: By Category ──
    with t3:
        with st.spinner("Loading category P&L…"):
            cat = get_pnl_category(where, sfx)
        _render_breakdown(cat, "CATEGORY", "Category",
                          "Category P&amp;L", "dl_pnl_cat", "category")

    # ── Tab 4: By Channel ──
    with t4:
        with st.spinner("Loading channel P&L…"):
            ch = get_pnl_channel(where, sfx)
        _render_breakdown(ch, "CHANNEL", "Channel",
                          "Channel P&amp;L", "dl_pnl_chan", "channel")

    # ── Tab 5: By Country ──
    with t5:
        with st.spinner("Loading country P&L…"):
            geo = get_pnl_geo(where, sfx)
        _render_breakdown(geo, "GEO", "Country",
                          "Country P&amp;L", "dl_pnl_geo", "country")


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTER
# ═══════════════════════════════════════════════════════════════════════════════

# ── SKU / ASIN search (shown above any view) ──
if sku_search and sku_search.strip():
    with st.expander(f"🔍 Search: '{sku_search.strip()}'", expanded=True):
        with st.spinner("Searching…"):
            sk = get_sku_lookup(sku_search.strip(), d_from, d_to, sfx)
        if sk.empty:
            st.info(f"📭 No ASINs match '{sku_search.strip()}' in {d_from.strftime('%d %b')} – {d_to.strftime('%d %b %Y')}.")
        else:
            s = sk.copy()
            s["Act Rev"]  = sk["ACT_REV"].apply(fmt_lakhs)
            s["Bud Rev"]  = sk["BUD_REV"].apply(fmt_lakhs)
            s["CM2 Abs"]  = sk["CM2_ABS"].apply(fmt_lakhs)
            s["Rev %"]    = sk["REV_PCT"].apply(fmt_pct)
            _rv = pd.to_numeric(sk["REV_PCT"], errors="coerce").reset_index(drop=True)
            show_sk = s[["ASIN","PRODUCT","BRAND","GEO","SUB_CAT",
                          "Act Rev","Bud Rev","Rev %","CM2 Abs"]].reset_index(drop=True)

            def style_sk(row):
                sx  = [""] * len(row)
                idx = row.index.tolist()
                if "Rev %" in idx:
                    sx[idx.index("Rev %")] = color_pct(_rv.iloc[row.name])
                return sx

            st.dataframe(show_sk.style.apply(style_sk, axis=1).hide(axis="index"),
                         use_container_width=True)

view = st.session_state.view
if view == "ceo":
    render_ceo()
elif view == "overview":
    render_overview()
elif view == "subcategory":
    render_subcategory()
elif view == "pnl":
    render_pnl()
else:
    render_asin()
