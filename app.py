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
    page_icon="https://www.vahdam.com/cdn/shop/files/favicon.png",
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
        height: 220px; display: flex; flex-direction: column;
        justify-content: flex-start; gap: 4px;
    }
    .kpi-card .kpi-actual { margin-top: 2px; }
    .kpi-card .kpi-budget { flex: 0 0 auto; }
    .kpi-card .kpi-delta { margin-top: 2px; }
    /* Compare block (LMTD/LYMTD or LM/LY) — anchored at bottom of card */
    .kpi-compare {
        margin-top: auto; padding-top: 6px;
        border-top: 1px dashed #d6ccba;
        display: flex; flex-direction: column; gap: 2px;
    }
    .pop-line {
        display: flex; justify-content: space-between; align-items: center;
        font-size: 10.5px; font-weight: 600; letter-spacing: 0.3px;
    }
    .pop-tag {
        color: #AB8743; text-transform: uppercase; letter-spacing: 0.6px;
        font-size: 9.5px;
    }
    .pop-val { font-size: 11px; }
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
        border: 1px solid #d6ccba; border-top: 3px solid #004A2B; border-radius: 10px;
        padding: 12px 14px; text-align: center;
        box-shadow: 0 1px 4px rgba(0,74,43,0.05);
        height: 138px; display: flex; flex-direction: column;
        justify-content: flex-start; gap: 3px;
        transition: transform .15s ease, box-shadow .15s ease, border-color .15s ease;
    }
    .pnl-strip:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 14px rgba(0,74,43,0.12);
        border-top-color: #AB8743;
    }
    .pnl-strip-label { font-size: 10px; color: #AB8743; text-transform: uppercase;
                       letter-spacing: 1px; font-weight: 700; }
    .pnl-strip-val   { font-size: 20px; font-weight: 700; color: #004A2B; line-height: 1.1;
                       margin-top: 1px; }
    .pnl-strip-sub   { font-size: 10.5px; color: #7a6a50; margin-top: 1px; }
    .pnl-strip .kpi-delta { margin-top: auto; font-size: 11px; }
    .vs-b-pill {
        display: inline-block; border-radius: 12px; padding: 1px 10px;
        font-size: 10.5px; font-weight: 700; letter-spacing: 0.3px;
        margin: 2px auto 0 auto;
    }
    /* Adds vertical breathing room between successive KPI rows */
    .kpi-row-gap { height: 14px; }

    /* ── GEO performance bar list (Exec Summary) ── */
    .geo-perf {
        background: #ffffff; border: 1px solid #d6ccba; border-radius: 10px;
        padding: 14px 18px; box-shadow: 0 1px 4px rgba(0,74,43,0.05);
    }
    .geo-perf-row {
        display: grid; align-items: center;
        grid-template-columns: 60px 1fr 70px 180px;
        gap: 14px; padding: 6px 0;
        border-bottom: 1px dashed #ede4d0;
    }
    .geo-perf-row:last-child { border-bottom: none; }
    .geo-name { font-weight: 700; color: #004A2B; font-size: 14px;
                letter-spacing: 0.4px; }
    .geo-bar-track {
        position: relative; height: 14px; background: #f2eadb;
        border-radius: 7px; overflow: hidden;
    }
    .geo-bar-fill {
        position: absolute; top: 0; left: 0; height: 100%;
        border-radius: 7px;
        transition: width .3s ease;
    }
    .geo-bar-up   { background: linear-gradient(90deg, #6dba8d 0%, #1a7a3e 100%); }
    .geo-bar-warn { background: linear-gradient(90deg, #e8c87b 0%, #AB8743 100%); }
    .geo-bar-down { background: linear-gradient(90deg, #d35a4a 0%, #8b1a1a 100%); }
    /* 100% target marker (since track caps at 150%, marker sits at ⅔ width) */
    .geo-bar-mark {
        position: absolute; top: -3px; bottom: -3px; left: 66.66%;
        width: 2px; background: rgba(0,74,43,0.55); border-radius: 1px;
    }
    .geo-pct      { font-weight: 700; font-size: 13px; text-align: right; }
    .geo-pct-up   { color: #1a7a3e; }
    .geo-pct-warn { color: #AB8743; }
    .geo-pct-down { color: #8b1a1a; }
    .geo-vals     { font-size: 11.5px; color: #7a6a50; text-align: right; }

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
    /* Make the dark Vahdam logo visible on dark green sidebar */
    section[data-testid="stSidebar"] img {
        filter: brightness(0) invert(1) opacity(0.95);
        margin-bottom: 4px;
    }
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

    /* ── Compact action toolbar (top-right icons) ── */
    .action-toolbar {
        display: flex; justify-content: flex-end; align-items: center;
        gap: 8px; margin-top: 12px;
    }
    .ico-btn {
        display: inline-flex; align-items: center; justify-content: center;
        width: 36px; height: 36px; border-radius: 8px;
        background: #ffffff; border: 1px solid #d6ccba;
        text-decoration: none !important; font-size: 16px;
        box-shadow: 0 1px 3px rgba(0,74,43,0.06);
        transition: transform .12s ease, box-shadow .12s ease,
                    border-color .12s ease, background .12s ease;
        cursor: pointer; user-select: none;
    }
    .ico-btn:hover {
        transform: translateY(-1px);
        background: #faf5ea; border-color: #AB8743;
        box-shadow: 0 3px 8px rgba(0,74,43,0.12);
    }
    .ico-btn-done {
        background: #d6ece1 !important; border-color: #1a7a3e !important;
    }

    /* ── Sidebar credit footer ── */
    .sb-credit {
        text-align: center; font-size: 10.5px; color: #AB8743;
        margin-top: 16px; letter-spacing: 0.3px;
    }
    .sb-credit .heart { color: #d35a4a; }

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
for k, v in [("view","ceo"), ("selected_geo",None), ("selected_subcat",None),
             ("selected_asin",None), ("selected_asin_product",None)]:
    if k not in st.session_state: st.session_state[k] = v

# Hydrate from URL on first load (#19)
if "_url_synced" not in st.session_state:
    try:
        qp = st.query_params
        if "view" in qp and qp["view"] in {"ceo","overview","subcategory","asin","asin_detail","pnl","price"}:
            st.session_state.view = qp["view"]
        if "geo" in qp:    st.session_state.selected_geo    = qp["geo"]
        if "subcat" in qp: st.session_state.selected_subcat = qp["subcat"]
        if "asin" in qp:   st.session_state.selected_asin   = qp["asin"]
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

    use_inr = st.radio("Currency",
                       ["INR (₹)", "Local ($, €, £, …)"],
                       index=0) == "INR (₹)"
    sfx = "INR" if use_inr else "LOCAL"
    sym = "₹" if use_inr else ""

    # ── Quick Date Presets ──
    st.markdown("#### Quick Presets")
    today  = date.today()
    PRESET_OPTS = ["MTD", "QTD", "YTD",
                   "Last 30 Days", "Last 60 Days", "Last 90 Days",
                   "Custom Range"]
    preset = st.selectbox("Date Preset", PRESET_OPTS, index=0, key="date_preset")

    _preset_days = {"Last 30 Days": 30, "Last 60 Days": 60, "Last 90 Days": 90}
    if preset == "MTD":
        d_from, d_to = today.replace(day=1), today
    elif preset == "QTD":
        # Quarter-to-date: first day of current quarter
        q_start_month = ((today.month - 1) // 3) * 3 + 1
        d_from = date(today.year, q_start_month, 1)
        d_to   = today
    elif preset == "YTD":
        d_from = date(today.year, 1, 1)
        d_to   = today
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

    st.markdown("#### Filters")
    if st.button("⟲ Clear all filters", use_container_width=True,
                 key="clear_filters",
                 help="Reset Brand / Category / Channel / GEO / Sub-Category / SKU search"):
        for k in ["flt_brand","flt_cat","flt_channel","flt_geo","flt_subcat","sku_search"]:
            st.session_state.pop(k, None)
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
    if st.button("Executive Summary", use_container_width=True, key="nav_ceo"):
        st.session_state.view = "ceo"
        st.rerun()
    if st.button("Overview", use_container_width=True, key="nav_overview"):
        st.session_state.view = "overview"
        st.rerun()
    if st.button("P&L Statement", use_container_width=True, key="nav_pnl"):
        st.session_state.view = "pnl"
        st.rerun()
    if st.button("Price Tracker", use_container_width=True, key="nav_price"):
        st.session_state.view = "price"
        st.rerun()

    # ── Refresh data ──
    st.markdown("---")
    if st.button("🔄 Refresh data", use_container_width=True, key="refresh_data",
                 help="Clear cache and refetch from Snowflake"):
        st.cache_data.clear()
        st.rerun()
    from datetime import datetime as _dt
    st.markdown(f"<div style='font-size:10.5px;color:#AB8743;text-align:center;"
                f"margin-top:4px;'>Last loaded · {_dt.now().strftime('%H:%M:%S')}"
                f"</div>", unsafe_allow_html=True)

    # ── Credit footer ──
    st.markdown(
        '<div class="sb-credit">Created with '
        '<span class="heart">❤</span> by <b>Raghuvansh</b></div>',
        unsafe_allow_html=True)

# ── Month / pro-rata helpers ──────────────────────────────────────────────────
month_start       = d_from.replace(day=1)
_total_days       = calendar.monthrange(d_from.year, d_from.month)[1]
month_end         = date(d_from.year, d_from.month, _total_days)
days_elapsed      = min((d_to - month_start).days + 1, _total_days)

# Previous comparable period (same length, immediately preceding)
_period_len       = (d_to - d_from).days + 1
prev_d_to         = d_from - timedelta(days=1)
prev_d_from       = prev_d_to - timedelta(days=_period_len - 1)

def _shift_month(d, months=-1):
    """Shift a date by N months, clamping day to last day of new month."""
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    last = calendar.monthrange(y, m)[1]
    return date(y, m, min(d.day, last))

def _shift_year(d, years=-1):
    """Shift a date by N years, Feb 29 → Feb 28 in non-leap years."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)

# Last Month same window (LM) — same dates shifted back 1 calendar month
lm_d_from = _shift_month(d_from, -1)
lm_d_to   = _shift_month(d_to,   -1)
# Last Year same window (LY) — same dates shifted back 1 year
ly_d_from = _shift_year(d_from, -1)
ly_d_to   = _shift_year(d_to,   -1)

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

GEO_SYMBOL = {
    "USA": "$", "UK": "£", "DE": "€", "FR": "€", "IT": "€", "ES": "€",
    "CA": "C$", "AUS": "A$", "UAE": "AED ",
}

def geo_sym(geo):
    """Currency symbol for a GEO, or empty string if unknown.
    Returns empty when global Local mode is off (so INR uses ₹ via sym)."""
    if use_inr: return "₹"
    return GEO_SYMBOL.get(geo, "")


def fmt_lakhs_for(v, geo, signed=False):
    """Format value with the country's local currency symbol (Local Currency mode)."""
    g_sym = geo_sym(geo)
    saved = globals().get("sym", "₹")
    try:
        globals()["sym"] = g_sym
        return fmt_lakhs(v, signed=signed)
    finally:
        globals()["sym"] = saved


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
            ROUND(SUM(CM1_ACTUAL_{sfx})/NULLIF(SUM(SALES_ACTUAL_{sfx}),0)*100,1) AS CM1_PCT_ACT,
            ROUND(SUM(CM1_BUDGET_{sfx})/NULLIF(SUM(SALES_BUDGET_{sfx}),0)*100,1) AS CM1_PCT_BUD,
            ROUND(SUM(PM_SPEND_ACTUAL_{sfx})/NULLIF(SUM(SALES_ACTUAL_{sfx}),0)*100,1) AS ACOS_PCT_ACT,
            ROUND(SUM(PM_SPEND_BUDGET_{sfx})/NULLIF(SUM(SALES_BUDGET_{sfx}),0)*100,1) AS ACOS_PCT_BUD,
            ROUND(SUM(CM2_BUDGET_{sfx}),0)    AS CM2_BUD,
            ROUND(SUM(CM2_ACTUAL_{sfx}),0)    AS CM2_ACT,
            ROUND(SUM(CM2_ACTUAL_{sfx})/NULLIF(SUM(SALES_ACTUAL_{sfx}),0)*100,1) AS CM2_PCT_ACT,
            ROUND(SUM(CM2_BUDGET_{sfx})/NULLIF(SUM(SALES_BUDGET_{sfx}),0)*100,1) AS CM2_PCT_BUD,
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
            ROUND(SUM(CM1_ACTUAL_{sfx})/NULLIF(SUM(SALES_ACTUAL_{sfx}),0)*100,1),
            ROUND(SUM(CM1_BUDGET_{sfx})/NULLIF(SUM(SALES_BUDGET_{sfx}),0)*100,1),
            ROUND(SUM(PM_SPEND_ACTUAL_{sfx})/NULLIF(SUM(SALES_ACTUAL_{sfx}),0)*100,1),
            ROUND(SUM(PM_SPEND_BUDGET_{sfx})/NULLIF(SUM(SALES_BUDGET_{sfx}),0)*100,1),
            ROUND(SUM(CM2_BUDGET_{sfx}),0),
            ROUND(SUM(CM2_ACTUAL_{sfx}),0),
            ROUND(SUM(CM2_ACTUAL_{sfx})/NULLIF(SUM(SALES_ACTUAL_{sfx}),0)*100,1),
            ROUND(SUM(CM2_BUDGET_{sfx})/NULLIF(SUM(SALES_BUDGET_{sfx}),0)*100,1),
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
def get_asin_daily(asin, geo, d1, d2, sfx):
    """Daily revenue/units/spend for one ASIN. P&L and marketing aggregated
    separately to avoid join row-multiplication, then merged in pandas."""
    a = asin.replace("'", "''")
    pnl = run_query(f"""
        SELECT DAY,
            COALESCE(ROUND(SUM(SALES_ACTUAL_{sfx}),0),0)  AS REVENUE,
            COALESCE(SUM(QTY_ACTUAL),0)                   AS UNITS,
            COALESCE(ROUND(SUM(SALES_BUDGET_{sfx}),0),0)  AS BUD_REVENUE,
            COALESCE(SUM(QTY_BUDGET),0)                   AS BUD_UNITS
        FROM {TABLE}
        WHERE DAY BETWEEN '{d1}' AND '{d2}'
          AND GEO = '{geo}' AND {GEO_EXCL}
          AND SPLIT_PART(ASIN,' ',1) = '{a}'
        GROUP BY DAY
    """)
    mkt = run_query(f"""
        SELECT DAY,
            COALESCE(ROUND(SUM(SPEND),0),0)        AS SPEND,
            COALESCE(ROUND(SUM(AD_SALES),0),0)     AS AD_SALES,
            COALESCE(ROUND(SUM(IMPRESSIONS),0),0)  AS IMPRESSIONS,
            COALESCE(ROUND(SUM(CLICKS),0),0)       AS CLICKS,
            COALESCE(ROUND(SUM(CONVERSIONS),0),0)  AS CONVERSIONS
        FROM {MKTG}
        WHERE DAY BETWEEN '{d1}' AND '{d2}'
          AND GEO = '{geo}'
          AND ASIN = '{a}'
        GROUP BY DAY
    """)
    if not pnl.empty: pnl["DAY"] = pd.to_datetime(pnl["DAY"])
    if not mkt.empty: mkt["DAY"] = pd.to_datetime(mkt["DAY"])
    merged = pd.merge(pnl, mkt, on="DAY", how="outer") if not (pnl.empty and mkt.empty) else pd.DataFrame()
    if merged.empty: return merged
    for c in ["REVENUE","UNITS","SPEND","AD_SALES","IMPRESSIONS","CLICKS","CONVERSIONS",
              "BUD_REVENUE","BUD_UNITS"]:
        if c not in merged.columns: merged[c] = 0
    merged = merged.fillna(0).sort_values("DAY").reset_index(drop=True)
    return merged


@st.cache_data(ttl=300, show_spinner=False)
def get_asin_totals(geo, sub_cat, d1, d2, sfx):
    """One-row totals for a (geo, sub_cat, date range).

    Aggregates P&L (table) and marketing (table) separately to avoid the JOIN
    duplicating P&L rows when one (day, asin) has multiple campaign rows.
    """
    esc = sub_cat.replace("'","''")
    if sub_cat == "(untagged)":
        pnl_subcat = "COALESCE(NULLIF(SUB_CATEGORY,''),'(untagged)') = '(untagged)'"
    else:
        pnl_subcat = f"UPPER(TRIM(COALESCE(SUB_CATEGORY,''))) = UPPER(TRIM('{esc}'))"

    pnl = run_query(f"""
        SELECT
            COALESCE(ROUND(SUM(SALES_ACTUAL_{sfx}),0),0)     AS ACT_REVENUE,
            COALESCE(ROUND(SUM(SALES_BUDGET_{sfx}),0),0)     AS BUD_REVENUE,
            COALESCE(ROUND(SUM(CM2_ACTUAL_{sfx}),0),0)       AS ACT_CM2_ABS,
            COALESCE(ROUND(SUM(CM2_BUDGET_{sfx}),0),0)       AS BUD_CM2_ABS,
            COALESCE(ROUND(SUM(PM_SPEND_ACTUAL_{sfx}),0),0)  AS PM_SPEND_ACT,
            COALESCE(ROUND(SUM(PM_SPEND_BUDGET_{sfx}),0),0)  AS PM_SPEND_BUD
        FROM {TABLE}
        WHERE DAY BETWEEN '{d1}' AND '{d2}'
          AND GEO = '{geo}' AND {GEO_EXCL}
          AND {pnl_subcat}
          AND ASIN IS NOT NULL AND ASIN != ''
    """)

    # ASINs present in this slice (so marketing totals stay scoped to the sub-cat)
    asins = run_query(f"""
        SELECT DISTINCT SPLIT_PART(ASIN,' ',1) AS A
        FROM {TABLE}
        WHERE DAY BETWEEN '{d1}' AND '{d2}'
          AND GEO = '{geo}' AND {GEO_EXCL}
          AND {pnl_subcat}
          AND ASIN IS NOT NULL AND ASIN != ''
    """)
    asin_list = ", ".join(repr(a) for a in asins["A"].dropna().tolist())
    if asin_list:
        mkt = run_query(f"""
            SELECT
                COALESCE(ROUND(SUM(SPEND),0),0)        AS PAID_SPEND,
                COALESCE(ROUND(SUM(AD_SALES),0),0)     AS PAID_REVENUE,
                COALESCE(ROUND(SUM(IMPRESSIONS),0),0)  AS IMPRESSIONS,
                COALESCE(ROUND(SUM(CLICKS),0),0)       AS CLICKS,
                COALESCE(ROUND(SUM(CONVERSIONS),0),0)  AS CONVERSIONS
            FROM {MKTG}
            WHERE DAY BETWEEN '{d1}' AND '{d2}'
              AND GEO = '{geo}'
              AND ASIN IN ({asin_list})
        """)
    else:
        mkt = pd.DataFrame([{"PAID_SPEND":0, "PAID_REVENUE":0, "IMPRESSIONS":0,
                             "CLICKS":0, "CONVERSIONS":0}])

    combined = pd.concat([pnl.reset_index(drop=True),
                          mkt.reset_index(drop=True)], axis=1)
    # Choose ad-spend source: prefer P&L's PM_SPEND_ACTUAL when present
    # (broader marketing spend), else fall back to marketing table SPEND.
    pm_act = _f(combined.iloc[0].get("PM_SPEND_ACT"))
    pm_bud = _f(combined.iloc[0].get("PM_SPEND_BUD"))
    if pm_act and pm_act > 0:
        combined["AD_SPEND_ACT"] = pm_act
        combined["AD_SPEND_BUD"] = pm_bud
    else:
        combined["AD_SPEND_ACT"] = _f(combined.iloc[0].get("PAID_SPEND")) or 0
        combined["AD_SPEND_BUD"] = pm_bud
    return combined


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


def strip_card(label, value, sub=None, delta=None, delta_suffix="vs LM",
               vs_b_pct=None, vs_b_lower_better=False):
    """Compact KPI card matching the P&L summary strip style. Reusable across views.

    vs_b_pct: optional achievement % vs budget (e.g. 101.2 means 1.2% above plan).
              Renders a small pill between the sub line and the delta line.
    vs_b_lower_better: when True (e.g. for ad spend), <100% is good (green).
    """
    # ── vs Budget pill ──
    vs_b_html = ""
    if vs_b_pct is not None:
        v = _f(vs_b_pct)
        if v is not None:
            if vs_b_lower_better:
                if v <= 100:    klass = "badge-green"
                elif v <= 110:  klass = "badge-amber"
                else:           klass = "badge-red"
            else:
                if v >= 100:    klass = "badge-green"
                elif v >= 90:   klass = "badge-amber"
                else:           klass = "badge-red"
            vs_b_html = (f'<div class="vs-b-pill {klass}">{v:.1f}% vs B</div>')

    # ── vs LM delta ──
    delta_html = ""
    if delta is not None:
        d = _f(delta)
        if d is not None:
            cls = "delta-up" if d >= 0 else "delta-dn"
            arrow = "▲" if d >= 0 else "▼"
            suffix_html = (f' <span class="small-muted" '
                           f'style="font-weight:500;">{delta_suffix}</span>'
                           if delta_suffix else "")
            delta_html = (f'<div class="kpi-delta {cls}">'
                          f'{arrow} {abs(d):.1f}%{suffix_html}</div>')

    sub_html = f'<div class="pnl-strip-sub">{sub}</div>' if sub else ""
    return (f'<div class="pnl-strip">'
            f'<div class="pnl-strip-label">{label}</div>'
            f'<div class="pnl-strip-val">{value}</div>'
            f'{sub_html}{vs_b_html}{delta_html}</div>')


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
def render_alerts(view1_df, kpi_row, agg_label="GEO", key_prefix="alert"):
    """Render a collapsible alerts banner with clickable GEO chips that drill
    into the Sub-Category view. Renders Streamlit widgets directly (no return)."""
    critical_rows, warn_rows = [], []
    if view1_df is not None and not view1_df.empty:
        totals = view1_df[view1_df["CHANNEL"] == "TOTAL"].copy()
        totals["REV_PCT_n"] = pd.to_numeric(totals["REV_PCT"], errors="coerce")
        totals = totals.dropna(subset=["REV_PCT_n"])
        critical_rows = totals[totals["REV_PCT_n"] < 80][["GEO", "REV_PCT_n"]] \
                            .values.tolist()
        warn_rows = totals[(totals["REV_PCT_n"] >= 80) & (totals["REV_PCT_n"] < 90)] \
                        [["GEO", "REV_PCT_n"]].values.tolist()

    margin_msgs = []
    if kpi_row is not None:
        acos_delta = _f(kpi_row.get("ACOS_DELTA"))
        if acos_delta is not None and acos_delta > 3:
            margin_msgs.append(("warn",
                f"📈 ACoS is {acos_delta:+.1f}pp above budget — "
                "review ad spend efficiency."))
        cm2_delta = _f(kpi_row.get("CM2_DELTA"))
        if cm2_delta is not None and cm2_delta < -2:
            margin_msgs.append(("danger",
                f"💸 CM2 margin is {cm2_delta:+.1f}pp below budget — "
                "profitability under pressure."))

    n_crit = len(critical_rows)
    n_warn = len(warn_rows)
    n_other = len(margin_msgs)
    if not (n_crit or n_warn or n_other):
        return

    # Single-line summary used as the expander title
    summary_bits = []
    if n_crit:  summary_bits.append(f"🚨 {n_crit} critical")
    if n_warn:  summary_bits.append(f"⚠️ {n_warn} watch")
    if n_other: summary_bits.append(
        f"📊 {n_other} margin alert{'s' if n_other != 1 else ''}")
    summary = "  ·  ".join(summary_bits)

    # Default open if any critical, otherwise collapsed
    with st.expander(f"{summary} — ⓘ details", expanded=bool(n_crit)):
        def _chip_row(label_html, rows, kind, key_kind):
            if not rows: return
            st.markdown(f'<div style="font-size:12.5px;color:{"#8b1a1a" if kind=="danger" else "#7a5c00"};'
                        f'font-weight:700;margin-bottom:6px;">{label_html}</div>',
                        unsafe_allow_html=True)
            # Up to 6 chips per row
            n_cols = min(len(rows), 6)
            cols = st.columns(n_cols + 1)  # extra spacer at the end
            for i, (geo, pct) in enumerate(rows[:n_cols]):
                with cols[i]:
                    if st.button(f"{geo}  {pct:.0f}%",
                                 key=f"{key_prefix}_{key_kind}_{geo}",
                                 use_container_width=True,
                                 help=f"Open {geo} sub-category breakdown"):
                        st.session_state.selected_geo    = geo
                        st.session_state.selected_subcat = None
                        st.session_state.view            = "subcategory"
                        st.rerun()
            # If more than 6, mention the rest
            if len(rows) > n_cols:
                extra = ", ".join(r[0] for r in rows[n_cols:])
                st.caption(f"… and {extra}")

        if n_crit:
            _chip_row("Below 80% of budget — click to investigate",
                      critical_rows, "danger", "crit")
        if n_warn:
            _chip_row("Between 80–90% of budget — keep watching",
                      warn_rows, "warn", "warn")
        for kind, msg in margin_msgs:
            (st.error if kind == "danger" else st.warning)(msg)


# ── Country performance bar with rich hover (Exec Summary) ──
def build_country_perf_chart(view1_df):
    """Horizontal bar chart of Revenue % vs Budget per country, with a rich
    hover tooltip showing all 5 KPIs (Rev, CM1%, ACoS%, CM2%, CM2 Abs)."""
    if not HAS_PLOTLY or view1_df is None or view1_df.empty:
        return None
    t = view1_df[view1_df["CHANNEL"] == "TOTAL"].copy()
    t["REV_PCT_n"] = pd.to_numeric(t["REV_PCT"], errors="coerce")
    t = t.dropna(subset=["REV_PCT_n"]).copy()
    if t.empty: return None
    t = t.sort_values("REV_PCT_n", ascending=True).reset_index(drop=True)

    def _num(col): return pd.to_numeric(t[col], errors="coerce") if col in t.columns else pd.Series([None]*len(t))

    cm1_act = _num("CM1_PCT_ACT"); cm1_bud = _num("CM1_PCT_BUD")
    acos_act= _num("ACOS_ACT");    acos_bud= _num("ACOS_BUD")
    cm2_act = _num("CM2_PCT_ACT"); cm2_bud = _num("CM2_PCT_BUD")
    cm2a    = _num("CM2_ABS_ACT"); cm2a_bud= _num("CM2_ABS_BUD")
    sales_act = _num("SALES_ACT"); sales_bud = _num("SALES_BUD")

    def _ppdiff(a, b):
        return [None if (pd.isna(x) or pd.isna(y)) else float(x) - float(y)
                for x, y in zip(a, b)]
    def _ratio(a, b):
        return [None if (pd.isna(x) or pd.isna(y) or float(y) == 0)
                else float(x) / float(y) * 100
                for x, y in zip(a, b)]

    def _pp_str(v):  return ("—" if v is None
                              else f"{'+' if v >= 0 else ''}{v:.1f}pp")
    def _pct_str(v): return ("—" if v is None
                              else f"{v:.1f}%")

    customdata = []
    for i, row in t.iterrows():
        cd = [
            fmt_lakhs(sales_act.iloc[i]),     fmt_lakhs(sales_bud.iloc[i]),
            f"{_f(t['REV_PCT_n'].iloc[i]):.1f}%",
            _pct_str(_f(cm1_act.iloc[i])),    _pct_str(_f(cm1_bud.iloc[i])),
            _pp_str(_ppdiff([cm1_act.iloc[i]], [cm1_bud.iloc[i]])[0]),
            _pct_str(_f(acos_act.iloc[i])),   _pct_str(_f(acos_bud.iloc[i])),
            _pp_str(_ppdiff([acos_act.iloc[i]], [acos_bud.iloc[i]])[0]),
            _pct_str(_f(cm2_act.iloc[i])),    _pct_str(_f(cm2_bud.iloc[i])),
            _pp_str(_ppdiff([cm2_act.iloc[i]], [cm2_bud.iloc[i]])[0]),
            fmt_lakhs(cm2a.iloc[i]),          fmt_lakhs(cm2a_bud.iloc[i]),
            (f"{_ratio([cm2a.iloc[i]],[cm2a_bud.iloc[i]])[0]:.1f}%"
              if _ratio([cm2a.iloc[i]],[cm2a_bud.iloc[i]])[0] is not None else "—"),
        ]
        customdata.append(cd)

    # Color per row: green ≥100, amber 90-99, red <90
    def _bar_color(v):
        if v is None: return "#7a6a50"
        if v >= 100: return "#1a7a3e"
        if v >= 90:  return "#AB8743"
        return "#8b1a1a"
    colors = [_bar_color(_f(v)) for v in t["REV_PCT_n"]]

    rev_x = [min(max(_f(v) or 0, 0), 150) for v in t["REV_PCT_n"]]
    labels = [f"{_f(v):.1f}%" if _f(v) is not None else "—" for v in t["REV_PCT_n"]]

    fig = go.Figure(go.Bar(
        x=rev_x,
        y=t["GEO"],
        orientation="h",
        marker=dict(color=colors,
                    line=dict(color="rgba(0,74,43,0.45)", width=1)),
        text=labels, textposition="outside",
        textfont=dict(size=12, color="#171717", family="Arial"),
        customdata=customdata,
        hovertemplate=(
            "<b style='font-size:13px;'>%{y}</b>  "
            "<span style='color:#7a6a50;'>· Rev vs Budget</span><br>"
            "──────────────────<br>"
            "<b>Revenue</b>      %{customdata[0]}  /  %{customdata[1]}  "
            "<b>(%{customdata[2]})</b><br>"
            "<b>CM1%</b>         %{customdata[3]}  /  %{customdata[4]}  "
            "<b>(%{customdata[5]} vs B)</b><br>"
            "<b>ACoS%</b>        %{customdata[6]}  /  %{customdata[7]}  "
            "<b>(%{customdata[8]} vs B)</b><br>"
            "<b>CM2%</b>         %{customdata[9]}  /  %{customdata[10]}  "
            "<b>(%{customdata[11]} vs B)</b><br>"
            "<b>CM2 Abs</b>      %{customdata[12]} /  %{customdata[13]}  "
            "<b>(%{customdata[14]})</b><br>"
            "<span style='color:#7a6a50;font-size:10px;'>"
            "Actual / Budget · click row to drill</span>"
            "<extra></extra>"
        ),
    ))
    # 100% target marker line
    fig.add_vline(x=100, line_dash="dash", line_color="rgba(0,74,43,0.55)",
                  line_width=2,
                  annotation_text="100% target",
                  annotation_position="top",
                  annotation_font=dict(size=10, color="#004A2B"))

    n = len(t)
    fig.update_layout(
        plot_bgcolor="#FBF5EA", paper_bgcolor="#FBF5EA",
        font=dict(family="Arial", color="#171717"),
        height=max(220, 44 + n * 36),
        margin=dict(l=50, r=80, t=30, b=30),
        showlegend=False,
        hoverlabel=dict(bgcolor="#ffffff",
                        font=dict(size=12, color="#171717", family="Arial"),
                        bordercolor="#004A2B", align="left"),
        xaxis=dict(title="", range=[0, 150],
                   gridcolor="rgba(171,135,67,0.15)",
                   zerolinecolor="rgba(171,135,67,0.4)",
                   ticksuffix="%"),
        yaxis=dict(title="", autorange="reversed",
                   gridcolor="rgba(0,0,0,0)",
                   tickfont=dict(size=13, color="#004A2B", family="Arial")),
        bargap=0.45,
    )
    return fig


# ── Sub-Category performance bar with rich hover ──
def build_subcat_perf_chart(view2_df):
    """Horizontal bar chart of Revenue % vs Budget per sub-category, with a rich
    hover tooltip showing all 5 KPIs (Rev, CM1%, ACoS%, CM2%, CM2 Abs).
    Mirrors build_country_perf_chart for visual consistency."""
    if not HAS_PLOTLY or view2_df is None or view2_df.empty:
        return None
    t = view2_df[view2_df["SUB_CATEGORY"] != "GRAND TOTAL"].copy()
    t["REV_PCT_n"] = pd.to_numeric(t["REV_PCT"], errors="coerce")
    t = t.dropna(subset=["REV_PCT_n"]).copy()
    if t.empty: return None
    t = t.sort_values("REV_PCT_n", ascending=True).reset_index(drop=True)

    def _num(col): return pd.to_numeric(t[col], errors="coerce") if col in t.columns else pd.Series([None]*len(t))

    sales_act = _num("SALES_ACT");   sales_bud = _num("SALES_BUD")
    cm1_act_p = _num("CM1_PCT_ACT"); cm1_bud_p = _num("CM1_PCT_BUD")
    acos_act_p= _num("ACOS_PCT_ACT");acos_bud_p= _num("ACOS_PCT_BUD")
    cm2_act_p = _num("CM2_PCT_ACT"); cm2_bud_p = _num("CM2_PCT_BUD")
    cm2a      = _num("CM2_ACT");     cm2a_bud  = _num("CM2_BUD")

    def _pp_str(a, b):
        if pd.isna(a) or pd.isna(b): return "—"
        v = float(a) - float(b)
        return f"{'+' if v >= 0 else ''}{v:.1f}pp"
    def _pct_str(v):
        return "—" if pd.isna(v) else f"{float(v):.1f}%"
    def _ratio_str(a, b):
        if pd.isna(a) or pd.isna(b) or float(b) == 0: return "—"
        return f"{float(a)/float(b)*100:.1f}%"

    customdata = []
    for i, row in t.iterrows():
        cd = [
            fmt_lakhs(sales_act.iloc[i]), fmt_lakhs(sales_bud.iloc[i]),
            f"{_f(t['REV_PCT_n'].iloc[i]):.1f}%",
            _pct_str(cm1_act_p.iloc[i]),  _pct_str(cm1_bud_p.iloc[i]),
            _pp_str(cm1_act_p.iloc[i], cm1_bud_p.iloc[i]),
            _pct_str(acos_act_p.iloc[i]), _pct_str(acos_bud_p.iloc[i]),
            _pp_str(acos_act_p.iloc[i], acos_bud_p.iloc[i]),
            _pct_str(cm2_act_p.iloc[i]),  _pct_str(cm2_bud_p.iloc[i]),
            _pp_str(cm2_act_p.iloc[i], cm2_bud_p.iloc[i]),
            fmt_lakhs(cm2a.iloc[i]),      fmt_lakhs(cm2a_bud.iloc[i]),
            _ratio_str(cm2a.iloc[i], cm2a_bud.iloc[i]),
        ]
        customdata.append(cd)

    def _bar_color(v):
        if v is None: return "#7a6a50"
        if v >= 100: return "#1a7a3e"
        if v >= 90:  return "#AB8743"
        return "#8b1a1a"
    colors = [_bar_color(_f(v)) for v in t["REV_PCT_n"]]

    rev_x = [min(max(_f(v) or 0, 0), 200) for v in t["REV_PCT_n"]]
    labels = [f"{_f(v):.1f}%" if _f(v) is not None else "—" for v in t["REV_PCT_n"]]

    fig = go.Figure(go.Bar(
        x=rev_x,
        y=t["SUB_CATEGORY"],
        orientation="h",
        marker=dict(color=colors,
                    line=dict(color="rgba(0,74,43,0.45)", width=1)),
        text=labels, textposition="outside",
        textfont=dict(size=12, color="#171717", family="Arial"),
        customdata=customdata,
        hovertemplate=(
            "<b style='font-size:13px;'>%{y}</b>  "
            "<span style='color:#7a6a50;'>· Rev vs Budget</span><br>"
            "──────────────────<br>"
            "<b>Revenue</b>      %{customdata[0]}  /  %{customdata[1]}  "
            "<b>(%{customdata[2]})</b><br>"
            "<b>CM1%</b>         %{customdata[3]}  /  %{customdata[4]}  "
            "<b>(%{customdata[5]} vs B)</b><br>"
            "<b>ACoS%</b>        %{customdata[6]}  /  %{customdata[7]}  "
            "<b>(%{customdata[8]} vs B)</b><br>"
            "<b>CM2%</b>         %{customdata[9]}  /  %{customdata[10]}  "
            "<b>(%{customdata[11]} vs B)</b><br>"
            "<b>CM2 Abs</b>      %{customdata[12]} /  %{customdata[13]}  "
            "<b>(%{customdata[14]})</b><br>"
            "<span style='color:#7a6a50;font-size:10px;'>"
            "Actual / Budget · click bar to drill into ASINs</span>"
            "<extra></extra>"
        ),
    ))
    fig.add_vline(x=100, line_dash="dash", line_color="rgba(0,74,43,0.55)",
                  line_width=2,
                  annotation_text="100% target",
                  annotation_position="top",
                  annotation_font=dict(size=10, color="#004A2B"))

    n = len(t)
    fig.update_layout(
        plot_bgcolor="#FBF5EA", paper_bgcolor="#FBF5EA",
        font=dict(family="Arial", color="#171717"),
        height=max(220, 44 + n * 36),
        margin=dict(l=50, r=90, t=30, b=30),
        showlegend=False,
        hoverlabel=dict(bgcolor="#ffffff",
                        font=dict(size=12, color="#171717", family="Arial"),
                        bordercolor="#004A2B", align="left"),
        xaxis=dict(title="", range=[0, max(160, (max(rev_x) if rev_x else 100) + 25)],
                   gridcolor="rgba(171,135,67,0.15)",
                   zerolinecolor="rgba(171,135,67,0.4)",
                   ticksuffix="%"),
        yaxis=dict(title="", autorange="reversed",
                   gridcolor="rgba(0,0,0,0)",
                   tickfont=dict(size=13, color="#004A2B", family="Arial")),
        bargap=0.45,
    )
    return fig


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
    if "view" in qp and qp["view"] in {"ceo","overview","subcategory","asin","pnl","price"}:
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
    sales_act = _f(row.get("SALES_ACT"))
    sales_bud = _f(row.get("SALES_BUD"))
    for label, row_type, pfx in _PNL_LINES:
        act = _f(row.get(f"{pfx}_ACT"))
        bud = _f(row.get(f"{pfx}_BUD"))
        if act is not None and bud is not None:
            var     = act - bud
            var_pct = (var / abs(bud) * 100) if bud != 0 else None
        else:
            var, var_pct = None, None
        # Common-size: each line as % of Sales
        pct_act = (act / sales_act * 100) if (act is not None and sales_act not in (None, 0)) else None
        pct_bud = (bud / sales_bud * 100) if (bud is not None and sales_bud not in (None, 0)) else None

        def _pct_fmt(v):
            return "—" if v is None else f"{v:.1f}%"

        rows.append({
            "P&L Line":       label,
            "Actual (INR)":   fmt_indian(act),
            "% of Sales (A)": _pct_fmt(pct_act),
            "Budget (INR)":   fmt_indian(bud),
            "% of Sales (B)": _pct_fmt(pct_bud),
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
    # Header row: title + page-sub on the left, compact action icons on the right
    _ht_col, _ha_col = st.columns([9, 3])
    with _ht_col:
        st.markdown('<div class="page-title">Executive Summary</div>',
                    unsafe_allow_html=True)
        st.markdown(
            f'<div class="page-sub">{d_from.strftime("%d %b %Y")} &rarr; {d_to.strftime("%d %b %Y")}'
            f' &nbsp;&bull;&nbsp; Currency: {"INR (₹)" if use_inr else "Local"}'
            f' &nbsp;&bull;&nbsp; {_period_len} days  &nbsp;&bull;&nbsp; '
            f'<span style="color:#7a6a50">vs prior {_period_len}d: '
            f'{prev_d_from.strftime("%d %b")}–{prev_d_to.strftime("%d %b")}</span></div>',
            unsafe_allow_html=True)
    with _ha_col:
        # Compact icon-only action toolbar (top-right)
        mail_subject = f"Vahdam Amazon P%26L — {d_from} to {d_to}"
        _toolbar = (
            f'<div class="action-toolbar">'
            f'<a href="#" class="ico-btn" title="Copy share link" '
            f"onclick=\"navigator.clipboard.writeText(window.location.href);"
            f"this.classList.add('ico-btn-done');setTimeout(()=>this.classList.remove('ico-btn-done'),1500);"
            f'return false;">🔗</a>'
            f'<a href="javascript:window.print()" class="ico-btn" '
            f'title="Print / Save PDF">🖨️</a>'
            f'<a href="mailto:?subject={mail_subject}" class="ico-btn" '
            f'title="Email summary">✉️</a>'
            f'</div>'
        )
        st.markdown(_toolbar, unsafe_allow_html=True)

    where      = build_where()
    where_lm   = build_where(date_from=lm_d_from, date_to=lm_d_to)
    where_fm   = build_where(date_from=month_start, date_to=month_end)
    kpi        = get_kpis(where, sfx)
    kpi_lm     = get_kpis(where_lm, sfx)
    kpi_fm     = get_kpis(where_fm, sfx)  # full-month budget for forecast
    df         = get_view1(where, sfx)

    if kpi.empty:
        st.warning("📭 No data found for the selected filters.")
        return
    k = kpi.iloc[0]
    klm = kpi_lm.iloc[0] if not kpi_lm.empty else None
    kfm = kpi_fm.iloc[0] if not kpi_fm.empty else None

    # Narrative
    narrative = build_narrative(k, df if not df.empty else None)
    if narrative:
        st.markdown(f'<div class="narrative">📊 {narrative}</div>',
                    unsafe_allow_html=True)

    # ── 5 KPI cards: Revenue · CM1% · ACoS% · CM2% · CM2 Abs ──
    def _ratio(act, bud):
        a, b = _f(act), _f(bud)
        if a is None or b is None or b == 0: return None
        return a / b * 100

    def _pct_change(cur, prev):
        c, p = _f(cur), _f(prev)
        if c is None or p is None or p == 0: return None
        return (c - p) / abs(p) * 100

    cards = [
        ("Revenue", fmt_lakhs(k.get("SALES_ACT")),
            f"Bud: {fmt_lakhs(k.get('SALES_BUD'))}",
            _pct_change(k.get("SALES_ACT"),
                        klm["SALES_ACT"] if klm is not None else None),
            _ratio(k.get("SALES_ACT"), k.get("SALES_BUD")), False),
        ("CM1%",    fmt_pct(k.get("CM1_ACT")),
            f"Bud: {fmt_pct(k.get('CM1_BUD'))}",
            _pct_change(k.get("CM1_ACT"),
                        klm["CM1_ACT"] if klm is not None else None),
            _ratio(k.get("CM1_ACT"), k.get("CM1_BUD")), False),
        ("ACoS%",   fmt_pct(k.get("ACOS_ACT")),
            f"Bud: {fmt_pct(k.get('ACOS_BUD'))}",
            _pct_change(k.get("ACOS_ACT"),
                        klm["ACOS_ACT"] if klm is not None else None),
            _ratio(k.get("ACOS_ACT"), k.get("ACOS_BUD")), True),
        ("CM2%",    fmt_pct(k.get("CM2_ACT")),
            f"Bud: {fmt_pct(k.get('CM2_BUD'))}",
            _pct_change(k.get("CM2_ACT"),
                        klm["CM2_ACT"] if klm is not None else None),
            _ratio(k.get("CM2_ACT"), k.get("CM2_BUD")), False),
        ("CM2 Abs", fmt_lakhs(k.get("CM2_ABS_ACT")),
            f"Bud: {fmt_lakhs(k.get('CM2_ABS_BUD'))}",
            _pct_change(k.get("CM2_ABS_ACT"),
                        klm["CM2_ABS_ACT"] if klm is not None else None),
            _ratio(k.get("CM2_ABS_ACT"), k.get("CM2_ABS_BUD")), False),
    ]
    cols = st.columns(5, gap="medium")
    for col, (lbl, val, sub, delta, ach, lb) in zip(cols, cards):
        col.markdown(strip_card(lbl, val, sub, delta=delta,
                                vs_b_pct=ach, vs_b_lower_better=lb),
                     unsafe_allow_html=True)

    # ── Forecast EOM (left) — gauges removed (redundant with vs-B pills above) ──
    if kfm is not None and days_elapsed > 0:
        mtd_where = build_where(date_from=month_start, date_to=min(d_to, month_end))
        mtd_kpi   = get_kpis(mtd_where, sfx)
        if not mtd_kpi.empty:
            mtd_act = _f(mtd_kpi.iloc[0].get("SALES_ACT"))
            mtd_bud = _f(kfm.get("SALES_BUD"))
            fc_html = forecast_card(mtd_act, mtd_bud, days_elapsed, _total_days)
            if fc_html:
                st.markdown('<div class="kpi-row-gap"></div>',
                            unsafe_allow_html=True)
                fc1, _ = st.columns([2, 5])
                with fc1:
                    st.markdown(fc_html, unsafe_allow_html=True)

    # ── Country Performance · interactive (Plotly, hover for full KPIs) ──
    if not df.empty:
        st.markdown('<div class="section-hdr" style="margin-top:18px;">'
                    'Country Performance · Revenue vs Budget '
                    '<span style="font-size:12px;color:#7a6a50;font-weight:500;">'
                    '— hover for full P&amp;L · click any bar to drill in</span>'
                    '</div>', unsafe_allow_html=True)
        cfig = build_country_perf_chart(df)
        if cfig is not None:
            cevent = st.plotly_chart(
                cfig, use_container_width=True,
                config={"displayModeBar": False},
                on_select="rerun",
                selection_mode=("points",),
                key="ceo_country_chart",
            )
            st.caption("Bars: Revenue % vs Budget. "
                       "🟢 ≥100% · 🟡 90–100% · 🔴 <90%. "
                       "100% target line shown. "
                       "**Click a bar** to drill into that country's sub-categories.")

            # Click-to-drill: navigate to Sub-Category view for the clicked GEO
            try:
                points = cevent.selection.points if cevent else []
            except Exception:
                points = []
            if points:
                clicked_geo = points[0].get("y") or points[0].get("label")
                if clicked_geo:
                    st.session_state.selected_geo    = clicked_geo
                    st.session_state.selected_subcat = None
                    st.session_state.view            = "subcategory"
                    st.rerun()

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

    # Mirror current state to URL params (for share link)
    write_state_to_url(st.session_state.view,
                       st.session_state.selected_geo,
                       st.session_state.selected_subcat,
                       st.session_state.get("date_preset", "MTD"),
                       st.session_state.get("sku_search", ""))

    # ── Drill into full dashboard ──
    # Country-level drill is handled by clicking the bar chart above.
    st.markdown("---")
    d1, d2 = st.columns(2)
    with d1:
        if st.button("Full Overview →", use_container_width=True,
                     key="ceo_to_overview"):
            st.session_state.view = "overview"; st.rerun()
    with d2:
        if st.button("P&L Statement →", use_container_width=True, key="ceo_to_pnl"):
            st.session_state.view = "pnl"; st.rerun()


def render_overview():
    st.markdown('<div class="page-title">Amazon P&amp;L Overview</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="page-sub">{d_from.strftime("%d %b %Y")} &rarr; {d_to.strftime("%d %b %Y")} '
        f'&nbsp;&bull;&nbsp; Currency: {"INR (₹)" if use_inr else "Local"} '
        f'&nbsp;&bull;&nbsp; Pace: {days_elapsed}/{_total_days} days elapsed</div>',
        unsafe_allow_html=True)

    where      = build_where()
    where_lm   = build_where(date_from=lm_d_from, date_to=lm_d_to)
    where_ly   = build_where(date_from=ly_d_from, date_to=ly_d_to)
    where_fm   = build_where(date_from=month_start, date_to=month_end)
    kpi        = get_kpis(where, sfx)
    kpi_lm     = get_kpis(where_lm, sfx)
    kpi_ly     = get_kpis(where_ly, sfx)

    if kpi.empty:
        st.warning("📭 No data found for the selected filters. Try widening the date range or clearing some filters.")
        return
    k = kpi.iloc[0]
    klm = kpi_lm.iloc[0] if not kpi_lm.empty else None
    kly = kpi_ly.iloc[0] if not kpi_ly.empty else None

    # Pre-fetch GEO breakdown so we can build narrative + movers above KPIs
    df    = get_view1(where, sfx)
    fm_df = get_fm_budget_v1(where_fm, sfx)

    # ── Auto-narrative (#1) ──
    narrative = build_narrative(k, df if not df.empty else None)
    if narrative:
        st.markdown(f'<div class="narrative">📊 {narrative}</div>',
                    unsafe_allow_html=True)

    # ── KPI Cards with LM + LY comparisons (#2) ──
    def _delta_vs(prev_row, key_act, mode="ratio"):
        """Return delta vs the given prior-period row: ratio = %change, pp = pp diff."""
        if prev_row is None: return None
        cur, prev = _f(k.get(key_act)), _f(prev_row.get(key_act))
        if cur is None or prev is None: return None
        if mode == "pp":   return cur - prev
        if prev == 0:      return None
        return (cur - prev) / abs(prev) * 100

    is_mtd = st.session_state.get("date_preset") == "MTD"
    lm_label = "LMTD" if is_mtd else "LM"
    ly_label = "LYMTD" if is_mtd else "LY"

    # CM2 Abs achievement % for the badge
    _cm2_abs_ach = None
    _cm2_abs_act_v, _cm2_abs_bud_v = _f(k.get("CM2_ABS_ACT")), _f(k.get("CM2_ABS_BUD"))
    if _cm2_abs_act_v is not None and _cm2_abs_bud_v not in (None, 0):
        _cm2_abs_ach = _cm2_abs_act_v / _cm2_abs_bud_v * 100

    cols = st.columns(5, gap="medium")
    cards = [
        ("Revenue vs Budget", "REV_BUDGET", fmt_lakhs(k["SALES_ACT"]), f"Bud: {fmt_lakhs(k['SALES_BUD'])}", k["REV_PCT"],
         kpi_delta(k["REV_DELTA"]),
         _delta_vs(klm, "SALES_ACT"),     _delta_vs(kly, "SALES_ACT")),
        ("CM1% vs Budget", "CM1", fmt_pct(k["CM1_ACT"]),    f"Bud: {fmt_pct(k['CM1_BUD'])}",     None,
         kpi_delta(k["CM1_DELTA"], unit="pp"),
         _delta_vs(klm, "CM1_ACT", "pp"),  _delta_vs(kly, "CM1_ACT", "pp")),
        ("ACoS%", "ACOS",              fmt_pct(k["ACOS_ACT"]),   f"Bud: {fmt_pct(k['ACOS_BUD'])}",    None,
         kpi_delta(k["ACOS_DELTA"], unit="pp", invert=True),
         _delta_vs(klm, "ACOS_ACT", "pp"), _delta_vs(kly, "ACOS_ACT", "pp")),
        ("CM2%", "CM2",               fmt_pct(k["CM2_ACT"]),    f"Bud: {fmt_pct(k['CM2_BUD'])}",     None,
         kpi_delta(k["CM2_DELTA"], unit="pp"),
         _delta_vs(klm, "CM2_ACT", "pp"),  _delta_vs(kly, "CM2_ACT", "pp")),
        ("CM2 Absolute", "CM2_ABS",       fmt_lakhs(k["CM2_ABS_ACT"]), f"Bud: {fmt_lakhs(k['CM2_ABS_BUD'])}", _cm2_abs_ach,
         kpi_delta(k["CM2_ABS_DELTA"]),
         _delta_vs(klm, "CM2_ABS_ACT"),    _delta_vs(kly, "CM2_ABS_ACT")),
    ]
    for col, (label, def_key, actual, budget, pct, delta, d_lm, d_ly) in zip(cols, cards):
        badge = pct_badge(pct) if pct is not None else ""

        def _delta_line(lbl, val, is_pp):
            if val is None:
                return (f'<div class="pop-line"><span class="pop-tag">{lbl}</span>'
                        f'<span class="pop-val small-muted">—</span></div>')
            cls = "delta-up" if val >= 0 else "delta-dn"
            arrow = "▲" if val >= 0 else "▼"
            unit  = "pp" if is_pp else "%"
            return (f'<div class="pop-line"><span class="pop-tag">{lbl}</span>'
                    f'<span class="pop-val {cls}">{arrow} {abs(val):.1f}{unit}</span></div>')

        is_pp = "%" in label
        compare_block = (f'<div class="kpi-compare">'
                         f'{_delta_line(lm_label, d_lm, is_pp)}'
                         f'{_delta_line(ly_label, d_ly, is_pp)}'
                         f'</div>')

        tip = METRIC_DEFS.get(def_key, "")
        label_html = (f'<div class="kpi-label" data-tip="{tip}">{label} ⓘ</div>'
                      if tip else f'<div class="kpi-label">{label}</div>')
        inner = "".join([
            label_html,
            f'<div class="kpi-actual">{actual}</div>',
            f'<div class="kpi-budget">{budget}</div>',
            delta or "",
            badge or "",
            compare_block,
        ])
        col.markdown(f'<div class="kpi-card">{inner}</div>',
                     unsafe_allow_html=True)
    st.caption(f"📅 **{lm_label}** = {lm_d_from.strftime('%d %b %Y')} – "
               f"{lm_d_to.strftime('%d %b %Y')}  ·  **{ly_label}** = "
               f"{ly_d_from.strftime('%d %b %Y')} – {ly_d_to.strftime('%d %b %Y')}")

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

    # Local-currency mode → use the country's own symbol per row
    if use_inr:
        _money = lambda v, geo, signed=False: fmt_lakhs(v, signed=signed)
    else:
        _money = lambda v, geo, signed=False: fmt_lakhs_for(v, geo, signed=signed)

    disp["Revenue Act"]  = disp.apply(lambda r: _money(r["SALES_ACT"],     r["GEO"]), axis=1)
    disp["Revenue Bud"]  = disp.apply(lambda r: _money(r["SALES_BUD"],     r["GEO"]), axis=1)
    disp["CM1% Act"]     = disp["CM1_PCT_ACT"].apply(fmt_pct)
    disp["CM1% Bud"]     = disp["CM1_PCT_BUD"].apply(fmt_pct)
    disp["ACoS% Act"]    = disp["ACOS_ACT"].apply(fmt_pct)
    disp["ACoS% Bud"]    = disp["ACOS_BUD"].apply(fmt_pct)
    disp["CM2% Act"]     = disp["CM2_PCT_ACT"].apply(fmt_pct)
    disp["CM2% Bud"]     = disp["CM2_PCT_BUD"].apply(fmt_pct)
    disp["CM2 Abs Act"]  = disp.apply(lambda r: _money(r["CM2_ABS_ACT"], r["GEO"]), axis=1)
    disp["CM2 Abs Bud"]  = disp.apply(lambda r: _money(r["CM2_ABS_BUD"], r["GEO"]), axis=1)
    disp["Rev % Achvd"]  = disp["REV_PCT"].apply(fmt_pct)
    disp["CM2 Abs %"]    = disp["CM2_ABS_ACHVD_PCT"].apply(fmt_pct)
    disp["CM2 Var"]      = disp.apply(lambda r: _money(r["CM2_VAR"], r["GEO"], signed=True), axis=1)
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
    where_lm = build_where(geo_override=geo, date_from=lm_d_from, date_to=lm_d_to)
    df       = get_view2(where, sfx)
    fm_df    = get_fm_budget_v2(where_fm, sfx)

    if df.empty:
        st.warning("📭 No sub-category data found for this selection.")
        return

    df = df.merge(fm_df[["SUB_CATEGORY","FM_SALES_BUD"]], on="SUB_CATEGORY", how="left")

    # ── KPI cards: Revenue · CM1% · ACoS% · CM2% · CM2 Abs ──
    # Use get_kpis for the GEO slice — same metrics as Overview, scoped to this GEO.
    k_now = get_kpis(where, sfx)
    k_lm  = get_kpis(where_lm, sfx)
    if not k_now.empty:
        k  = k_now.iloc[0]
        kl = k_lm.iloc[0] if not k_lm.empty else None

        def _ratio(act, bud):
            a, b = _f(act), _f(bud)
            if a is None or b is None or b == 0: return None
            return a / b * 100

        def _pct_change(cur, prev):
            c, p = _f(cur), _f(prev)
            if c is None or p is None or p == 0: return None
            return (c - p) / abs(p) * 100

        cards = [
            ("Revenue", fmt_lakhs(k.get("SALES_ACT")),
                f"Bud: {fmt_lakhs(k.get('SALES_BUD'))}",
                _pct_change(k.get("SALES_ACT"),
                            kl["SALES_ACT"] if kl is not None else None),
                _ratio(k.get("SALES_ACT"), k.get("SALES_BUD")), False),
            ("CM1%",    fmt_pct(k.get("CM1_ACT")),
                f"Bud: {fmt_pct(k.get('CM1_BUD'))}",
                _pct_change(k.get("CM1_ACT"),
                            kl["CM1_ACT"] if kl is not None else None),
                _ratio(k.get("CM1_ACT"), k.get("CM1_BUD")), False),
            ("ACoS%",   fmt_pct(k.get("ACOS_ACT")),
                f"Bud: {fmt_pct(k.get('ACOS_BUD'))}",
                _pct_change(k.get("ACOS_ACT"),
                            kl["ACOS_ACT"] if kl is not None else None),
                _ratio(k.get("ACOS_ACT"), k.get("ACOS_BUD")), True),  # lower = better
            ("CM2%",    fmt_pct(k.get("CM2_ACT")),
                f"Bud: {fmt_pct(k.get('CM2_BUD'))}",
                _pct_change(k.get("CM2_ACT"),
                            kl["CM2_ACT"] if kl is not None else None),
                _ratio(k.get("CM2_ACT"), k.get("CM2_BUD")), False),
            ("CM2 Abs", fmt_lakhs(k.get("CM2_ABS_ACT")),
                f"Bud: {fmt_lakhs(k.get('CM2_ABS_BUD'))}",
                _pct_change(k.get("CM2_ABS_ACT"),
                            kl["CM2_ABS_ACT"] if kl is not None else None),
                _ratio(k.get("CM2_ABS_ACT"), k.get("CM2_ABS_BUD")), False),
        ]
        cols = st.columns(5, gap="medium")
        for col, (lbl, val, sub, delta, ach, lb) in zip(cols, cards):
            col.markdown(strip_card(lbl, val, sub, delta=delta,
                                    vs_b_pct=ach, vs_b_lower_better=lb),
                         unsafe_allow_html=True)
        st.markdown("")

    # ── Sub-Category interactive performance chart ──
    st.markdown(
        '<div class="section-hdr">Sub-Category Performance · Revenue vs Budget '
        '<span style="font-size:12px;color:#7a6a50;font-weight:500;">'
        '— hover for full P&amp;L · click any bar to drill into ASINs</span>'
        '</div>', unsafe_allow_html=True)
    scfig = build_subcat_perf_chart(df)
    if scfig is not None:
        sc_evt = st.plotly_chart(
            scfig, use_container_width=True,
            config={"displayModeBar": False},
            on_select="rerun",
            selection_mode=("points",),
            key=f"subcat_chart_{geo}",
        )
        try:
            sc_points = sc_evt.selection.points if sc_evt else []
        except Exception:
            sc_points = []
        if sc_points:
            clicked_sc = sc_points[0].get("y") or sc_points[0].get("label")
            if clicked_sc:
                st.session_state.selected_subcat = clicked_sc
                st.session_state.view = "asin"
                st.rerun()
        st.caption("Bars: Revenue % vs Budget. 🟢 ≥100% · 🟡 90–100% · 🔴 <90%. "
                   "**Click a bar** to open that sub-category's ASIN view.")

    st.markdown('<div class="section-hdr">Sub-Category P&amp;L Table · '
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
    # Period totals (current) — query aggregates P&L and marketing separately
    # so the JOIN doesn't multiply P&L budgets by campaign-row count.
    _totals = get_asin_totals(geo, subcat, d_from, d_to, sfx)
    if not _totals.empty:
        t = _totals.iloc[0]
        act_rev  = _f(t["ACT_REVENUE"])
        bud_rev  = _f(t["BUD_REVENUE"])
        act_cm2  = _f(t["ACT_CM2_ABS"])
        bud_cm2  = _f(t["BUD_CM2_ABS"])
        ad_spd   = _f(t["AD_SPEND_ACT"])
        ad_bud   = _f(t["AD_SPEND_BUD"])
        paid_spd = _f(t["PAID_SPEND"])      # marketing-table only (for CTR/CVR/etc)
        paid_rev = _f(t["PAID_REVENUE"])
        impressions = _f(t["IMPRESSIONS"])
        clicks      = _f(t["CLICKS"])
        conversions = _f(t["CONVERSIONS"])
    else:
        act_rev = bud_rev = act_cm2 = bud_cm2 = ad_spd = ad_bud = None
        paid_spd = paid_rev = impressions = clicks = conversions = None

    # Prior-period totals (LM and LY) — for growth/loss deltas
    _lm = get_asin_totals(geo, subcat, lm_d_from, lm_d_to, sfx)
    _ly = get_asin_totals(geo, subcat, ly_d_from, ly_d_to, sfx)
    lm_row = _lm.iloc[0] if not _lm.empty else None
    ly_row = _ly.iloc[0] if not _ly.empty else None

    def _pct_change(cur, prev):
        if cur is None or prev is None or _f(prev) in (None, 0): return None
        return (_f(cur) - _f(prev)) / abs(_f(prev)) * 100

    # Ad efficiency uses ONLY marketing-table data (paid_spd, paid_rev) since
    # CTR/CVR/PACoS/CPC are paid-ads metrics by definition.
    # PACoS = Spend ÷ Paid Revenue × 100 (corrected: was inverted)
    pacos_pct = (paid_spd / paid_rev * 100) if (paid_spd and paid_rev) else None
    # TACoS = Spend ÷ Total Revenue × 100
    tacos_pct = (paid_spd / act_rev * 100) if (paid_spd and act_rev) else None
    # CVR = Conversions ÷ Clicks × 100
    cvr_pct = (conversions / clicks * 100) if (conversions and clicks) else None
    # CPC = Spend ÷ Clicks
    cpc_val = (paid_spd / clicks) if (paid_spd and clicks) else None
    # CTR = Clicks ÷ Impressions × 100
    ctr_pct = (clicks / impressions * 100) if (clicks and impressions) else None

    # Helpers for achievement % vs budget (None when budget is missing/zero)
    def _ach(act, bud):
        a, b = _f(act), _f(bud)
        if a is None or b is None or b == 0: return None
        return a / b * 100

    # Top row — enhanced KPI cards with budget + achievement vs B + % vs LM
    cards = [
        ("Total Revenue",  fmt_lakhs(act_rev),
            f"Bud: {fmt_lakhs(bud_rev)}" if bud_rev else None,
            _pct_change(act_rev, lm_row["ACT_REVENUE"] if lm_row is not None else None),
            _ach(act_rev, bud_rev), False),
        ("CM2 Absolute",   fmt_lakhs(act_cm2),
            f"Bud: {fmt_lakhs(bud_cm2)}" if bud_cm2 else None,
            _pct_change(act_cm2, lm_row["ACT_CM2_ABS"] if lm_row is not None else None),
            _ach(act_cm2, bud_cm2), False),
        ("Total Ad Spend", fmt_lakhs(ad_spd),
            f"Bud: {fmt_lakhs(ad_bud)}" if ad_bud else None,
            _pct_change(ad_spd, lm_row["AD_SPEND_ACT"] if lm_row is not None else None),
            _ach(ad_spd, ad_bud), True),  # lower = better for spend
        ("Paid Revenue",   fmt_lakhs(paid_rev),
            f"PACoS: {fmt_pct(pacos_pct)}" if pacos_pct is not None else None,
            _pct_change(paid_rev, lm_row["PAID_REVENUE"] if lm_row is not None else None),
            None, False),
        ("Impressions",
            f"{impressions/1e6:.2f}M" if impressions else "—",
            f"ASINs: {len(df):,}",
            _pct_change(impressions, lm_row["IMPRESSIONS"] if lm_row is not None else None),
            None, False),
    ]
    cols = st.columns(5, gap="medium")
    for col, (lbl, val, sub, delta, ach, lb) in zip(cols, cards):
        col.markdown(strip_card(lbl, val, sub, delta=delta,
                                vs_b_pct=ach, vs_b_lower_better=lb),
                     unsafe_allow_html=True)

    # Spacer between the two KPI rows
    st.markdown('<div class="kpi-row-gap"></div>', unsafe_allow_html=True)

    # Bottom row — ad efficiency KPIs (CVR, CPC, CTR, PACoS, TACoS).
    # No formulas — labels are self-explanatory.
    def _cpc_fmt(v):
        if v is None: return "—"
        return f"{sym}{v:,.2f}" if v >= 1 else f"{sym}{v:.2f}"

    def _lm_ratio(num_key, den_key, mult=1):
        if lm_row is None: return None
        n, d = _f(lm_row.get(num_key)), _f(lm_row.get(den_key))
        if not n or not d: return None
        return n / d * mult

    ads_cards = [
        ("CVR",    fmt_pct(cvr_pct),
            _pct_change(cvr_pct,   _lm_ratio("CONVERSIONS", "CLICKS", 100))),
        ("CPC",    _cpc_fmt(cpc_val),
            _pct_change(cpc_val,   _lm_ratio("PAID_SPEND", "CLICKS", 1))),
        ("CTR",    fmt_pct(ctr_pct),
            _pct_change(ctr_pct,   _lm_ratio("CLICKS", "IMPRESSIONS", 100))),
        ("PACoS%", fmt_pct(pacos_pct),
            _pct_change(pacos_pct, _lm_ratio("PAID_SPEND", "PAID_REVENUE", 100))),
        ("TACoS%", fmt_pct(tacos_pct),
            _pct_change(tacos_pct, _lm_ratio("PAID_SPEND", "ACT_REVENUE", 100))),
    ]
    cols2 = st.columns(5, gap="medium")
    for col, (lbl, val, delta) in zip(cols2, ads_cards):
        col.markdown(strip_card(lbl, val, sub=None, delta=delta),
                     unsafe_allow_html=True)
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

        st.caption("💡 **Click any row** to open the ASIN's daily deep-dive "
                   "(revenue, units, spend, ACoS, ASP over time).")
        evt_pnl = st.dataframe(
            p.style.apply(style_pnl, axis=1).hide(axis="index"),
            use_container_width=True, height=500,
            on_select="rerun",
            selection_mode="single-row",
            key=f"asin_pnl_table_{geo}_{subcat}")
        # Row click → drill into ASIN detail view
        try:
            rows = evt_pnl.selection.rows if evt_pnl else []
        except Exception:
            rows = []
        if rows:
            idx = rows[0]
            picked_asin = str(p.iloc[idx]["ASIN"])
            picked_prod = str(p.iloc[idx].get("Product", picked_asin))
            st.session_state.selected_asin         = picked_asin
            st.session_state.selected_asin_product = picked_prod
            st.session_state.view                  = "asin_detail"
            st.rerun()

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
def render_asin_detail():
    """Single-ASIN deep dive — daily revenue/units/spend with rich hover."""
    asin   = st.session_state.selected_asin
    prod   = st.session_state.selected_asin_product or asin
    geo    = st.session_state.selected_geo
    subcat = st.session_state.selected_subcat

    # ── Header + breadcrumbs ──
    c1, c2 = st.columns([1, 9])
    with c1:
        if st.button("← Back", key="asin_detail_back"):
            st.session_state.view = "asin"
            st.rerun()
    with c2:
        render_breadcrumbs([
            ("Overview",   "overview",    None,    None),
            (geo or "—",   "subcategory", geo,     None),
            (subcat or "—","asin",        geo,     subcat),
            (asin or "—",  "asin_detail", geo,     subcat),
        ])
        st.markdown(
            f'<div class="page-title">ASIN Deep Dive &mdash; {asin}</div>',
            unsafe_allow_html=True)
        st.markdown(
            f'<div class="page-sub" style="margin-bottom:8px;">'
            f'<span style="color:#004A2B;font-weight:600;">{prod}</span></div>',
            unsafe_allow_html=True)

    # ── Period selector (independent of global preset) ──
    p1, p2, p3 = st.columns([2, 5, 5])
    with p1:
        det_preset = st.selectbox(
            "Time window",
            ["Last 30 Days", "Last 7 Days", "Last 60 Days", "Last 90 Days",
             "MTD", "Match dashboard range"],
            index=0, key=f"asin_det_preset_{asin}")
    today_ = date.today()
    if det_preset == "Last 7 Days":
        d1, d2 = today_ - timedelta(days=6),  today_
    elif det_preset == "Last 30 Days":
        d1, d2 = today_ - timedelta(days=29), today_
    elif det_preset == "Last 60 Days":
        d1, d2 = today_ - timedelta(days=59), today_
    elif det_preset == "Last 90 Days":
        d1, d2 = today_ - timedelta(days=89), today_
    elif det_preset == "MTD":
        d1, d2 = today_.replace(day=1), today_
    else:
        d1, d2 = d_from, d_to

    with p2:
        st.markdown(
            f'<div style="font-size:12px;color:#7a6a50;padding-top:34px;">'
            f'📅 {d1.strftime("%d %b %Y")} – {d2.strftime("%d %b %Y")} · '
            f'{(d2 - d1).days + 1} days</div>', unsafe_allow_html=True)

    # ── Pull daily data ──
    with st.spinner("Loading ASIN daily…"):
        daily = get_asin_daily(asin, geo, d1, d2, sfx)

    if daily.empty:
        st.warning("📭 No daily data found for this ASIN in the selected window.")
        if st.button("← Back to ASIN list"):
            st.session_state.view = "asin"; st.rerun()
        return

    # ── Derived per-row metrics ──
    daily["ASP"]   = daily.apply(
        lambda r: (r["REVENUE"] / r["UNITS"]) if r["UNITS"] else None, axis=1)
    daily["ACOS"]  = daily.apply(
        lambda r: (r["SPEND"] / r["REVENUE"] * 100) if r["REVENUE"] else None, axis=1)
    daily["CVR"]   = daily.apply(
        lambda r: (r["CONVERSIONS"] / r["CLICKS"] * 100) if r["CLICKS"] else None, axis=1)

    # ── Period totals + Seller-Central-style summary cards ──
    rev_total  = _f(daily["REVENUE"].sum())
    units_tot  = _f(daily["UNITS"].sum())
    spend_tot  = _f(daily["SPEND"].sum())
    impr_tot   = _f(daily["IMPRESSIONS"].sum())
    asp_avg    = (rev_total / units_tot) if (rev_total and units_tot) else None
    acos_avg   = (spend_tot / rev_total * 100) if (rev_total and spend_tot) else None

    # 7/30/90-day comparable buckets (Amazon-style)
    def _window(days):
        cutoff = today_ - timedelta(days=days - 1)
        w = daily[daily["DAY"] >= pd.Timestamp(cutoff)]
        return w
    last7   = _window(7);   last30 = _window(30);   last90 = _window(90)

    def _sumlbl(slice_, col):
        v = _f(slice_[col].sum()) if not slice_.empty else None
        return v

    # Top summary strip
    cards = [
        ("Units · Window",       f"{units_tot:,.0f}" if units_tot else "—",
            f"{(units_tot/((d2-d1).days+1)):.0f}/day"
                if (units_tot and (d2-d1).days+1 > 0) else "—"),
        ("Revenue · Window",     fmt_lakhs(rev_total),
            f"Avg ASP: {sym}{asp_avg:,.2f}" if asp_avg else "—"),
        ("Ad Spend · Window",    fmt_lakhs(spend_tot),
            f"ACoS: {acos_avg:.1f}%" if acos_avg is not None else "—"),
        ("Impressions · Window", f"{impr_tot/1e6:.2f}M" if impr_tot else "—",
            f"Clicks: {_f(daily['CLICKS'].sum()):,.0f}"
                if _f(daily['CLICKS'].sum()) is not None else "—"),
    ]
    cols = st.columns(4, gap="medium")
    for col, (lbl, val, sub) in zip(cols, cards):
        col.markdown(strip_card(lbl, val, sub), unsafe_allow_html=True)

    # Seller-Central-style 7/30/90 mini-grid
    st.markdown("")
    st.markdown('<div class="section-hdr">Rolling windows</div>',
                unsafe_allow_html=True)
    rolling = pd.DataFrame([
        {"Window": "Last 7 days",
            "Units ordered": _sumlbl(last7, "UNITS"),
            "Revenue":       _sumlbl(last7, "REVENUE"),
            "Avg ASP": ((_sumlbl(last7, "REVENUE") or 0) / _sumlbl(last7, "UNITS"))
                        if _sumlbl(last7, "UNITS") else None,
            "Spend":         _sumlbl(last7, "SPEND")},
        {"Window": "Last 30 days",
            "Units ordered": _sumlbl(last30, "UNITS"),
            "Revenue":       _sumlbl(last30, "REVENUE"),
            "Avg ASP": ((_sumlbl(last30, "REVENUE") or 0) / _sumlbl(last30, "UNITS"))
                        if _sumlbl(last30, "UNITS") else None,
            "Spend":         _sumlbl(last30, "SPEND")},
        {"Window": "Last 90 days",
            "Units ordered": _sumlbl(last90, "UNITS"),
            "Revenue":       _sumlbl(last90, "REVENUE"),
            "Avg ASP": ((_sumlbl(last90, "REVENUE") or 0) / _sumlbl(last90, "UNITS"))
                        if _sumlbl(last90, "UNITS") else None,
            "Spend":         _sumlbl(last90, "SPEND")},
    ])
    rolling["Units ordered"] = rolling["Units ordered"].apply(
        lambda v: "—" if v is None else f"{v:,.0f}")
    rolling["Revenue"] = rolling["Revenue"].apply(fmt_lakhs)
    rolling["Avg ASP"] = rolling["Avg ASP"].apply(
        lambda v: "—" if v is None else f"{sym}{v:,.2f}")
    rolling["Spend"]   = rolling["Spend"].apply(fmt_lakhs)
    st.dataframe(rolling, use_container_width=True, hide_index=True)

    # ── Time-series chart with rich hover (Revenue, ASP, Units, Spend, ACoS) ──
    st.markdown("")
    metric_tabs = st.radio(
        "Show", ["Revenue", "Units", "Spend", "ACoS%"],
        horizontal=True, key=f"asin_det_metric_{asin}",
        label_visibility="collapsed")

    if HAS_PLOTLY:
        if metric_tabs == "Revenue":
            yvals = pd.to_numeric(daily["REVENUE"], errors="coerce")
            unit  = "Revenue"
        elif metric_tabs == "Units":
            yvals = pd.to_numeric(daily["UNITS"], errors="coerce")
            unit  = "Units"
        elif metric_tabs == "Spend":
            yvals = pd.to_numeric(daily["SPEND"], errors="coerce")
            unit  = "Spend"
        else:
            yvals = pd.to_numeric(daily["ACOS"], errors="coerce")
            unit  = "ACoS%"

        # Auto-scale for currency metrics
        peak = yvals.abs().max() or 0
        if metric_tabs in ("Revenue", "Spend"):
            if   peak >= 1e7: div, scale_lbl = 1e7, "Cr"
            elif peak >= 1e5: div, scale_lbl = 1e5, "L"
            elif peak >= 1e3: div, scale_lbl = 1e3, "K"
            else:             div, scale_lbl = 1, ""
        else:
            div, scale_lbl = 1, ""
        y_disp = yvals / div

        # Build rich hover with all metrics
        custom = []
        for i in range(len(daily)):
            r = daily.iloc[i]
            custom.append([
                fmt_lakhs(r["REVENUE"]),
                f"{sym}{(r['ASP'] or 0):,.2f}" if r["ASP"] else "—",
                f"{int(r['UNITS']):,}" if r["UNITS"] else "0",
                fmt_lakhs(r["SPEND"]) if r["SPEND"] else "—",
                f"{r['ACOS']:.1f}%" if r["ACOS"] is not None and r["ACOS"] >= 0 else "—",
                f"{int(r['IMPRESSIONS']):,}" if r["IMPRESSIONS"] else "0",
                f"{int(r['CLICKS']):,}" if r["CLICKS"] else "0",
            ])

        fig = go.Figure(go.Scatter(
            x=daily["DAY"], y=y_disp,
            mode="lines+markers",
            line=dict(color="#004A2B", width=2.5),
            marker=dict(size=6, color="#004A2B",
                        line=dict(width=1, color="#FBF5EA")),
            fill="tozeroy",
            fillcolor="rgba(0,74,43,0.08)",
            customdata=custom,
            hovertemplate=(
                "<b>%{x|%d %b %Y}</b>"
                "<br>──────────────────"
                "<br><b>Revenue</b>: %{customdata[0]}"
                "<br><b>ASP</b>: %{customdata[1]}"
                "<br><b>Units</b>: %{customdata[2]}"
                "<br>──────────────────"
                "<br><b>Ad Spend</b>: %{customdata[3]}"
                "<br><b>ACoS</b>: %{customdata[4]}"
                "<br><b>Impr</b>: %{customdata[5]}  |  "
                "<b>Clicks</b>: %{customdata[6]}"
                "<extra></extra>"
            ),
        ))
        title_unit = (f" ({sym} {scale_lbl})".rstrip()
                       if metric_tabs in ("Revenue", "Spend") else
                       (" (Units)" if metric_tabs == "Units" else " (%)"))
        fig.update_layout(
            title=dict(text=f"<b>{metric_tabs}</b> per day{title_unit}",
                       font=dict(size=15, color="#004A2B")),
            plot_bgcolor="#FBF5EA", paper_bgcolor="#FBF5EA",
            font=dict(family="Arial", color="#171717"),
            height=340, margin=dict(l=40, r=40, t=50, b=40),
            showlegend=False,
            hoverlabel=dict(bgcolor="#ffffff",
                            font=dict(color="#171717", family="Arial"),
                            bordercolor="#004A2B", align="left"),
        )
        fig.update_xaxes(gridcolor="rgba(171,135,67,0.15)",
                         tickformat="%d %b")
        fig.update_yaxes(gridcolor="rgba(171,135,67,0.15)",
                         title_text=metric_tabs +
                            (f" ({scale_lbl})" if scale_lbl else ""))
        st.plotly_chart(fig, use_container_width=True,
                        config={"displayModeBar": False})
        st.caption("Hover any day for the full daily snapshot · "
                   "switch metric above to retoggle the line shown.")

    # ── Daily detail table (downloadable) ──
    with st.expander("📄 Daily detail table", expanded=False):
        td = daily.copy()
        td["Date"]    = td["DAY"].dt.strftime("%d %b %Y")
        td["Revenue"] = td["REVENUE"].apply(fmt_lakhs)
        td["Units"]   = td["UNITS"].apply(
            lambda v: "—" if not v else f"{int(v):,}")
        td["ASP"]     = td["ASP"].apply(
            lambda v: "—" if v is None else f"{sym}{v:,.2f}")
        td["Spend"]   = td["SPEND"].apply(fmt_lakhs)
        td["ACoS"]    = td["ACOS"].apply(
            lambda v: "—" if v is None else f"{v:.1f}%")
        td["Impr"]    = td["IMPRESSIONS"].apply(
            lambda v: "—" if not v else f"{int(v):,}")
        td["Clicks"]  = td["CLICKS"].apply(
            lambda v: "—" if not v else f"{int(v):,}")
        show_cols = ["Date","Revenue","Units","ASP","Spend","ACoS","Impr","Clicks"]
        st.dataframe(td[show_cols].sort_values("Date", ascending=False),
                     use_container_width=True, height=320, hide_index=True)
        csv = td[show_cols].to_csv(index=False).encode("utf-8")
        st.download_button("📥 Download CSV", csv,
            file_name=f"asin_{asin}_{d1}_{d2}.csv",
            mime="text/csv", key=f"dl_asin_{asin}")


# ═══════════════════════════════════════════════════════════════════════════════
# PRICE TRACKER (Keepa)
# ═══════════════════════════════════════════════════════════════════════════════
# Domain codes per Keepa REST API: 1=US, 2=UK, 3=DE, 4=FR, 5=JP, 6=CA, 8=IT,
# 9=ES, 10=IN, 11=MX, 12=BR
KEEPA_DOMAIN = {"USA": 1, "UK": 2, "DE": 3, "FR": 4, "CA": 6,
                "IT": 8, "ES": 9, "AUS": 11, "UAE": 1}  # UAE/AUS fallback to US
# Currency symbol per Keepa domain
KEEPA_SYMBOL = {1: "$", 2: "£", 3: "€", 4: "€", 6: "C$", 8: "€",
                9: "€", 10: "₹", 11: "$"}

# ASINs to track per GEO. Add more here as the user grows the list.
_UK_ASINS = [
    "B0BJL537F1", "B0BJK5GPRD", "B0BJK7NW9F", "B0BB1LXSPN", "B0BJK93HN2",
    "B0BT7H247Z", "B0BFHKDK88", "B0BJK6L1G2", "B0B2928XNH", "B0C9CJ8L3N",
    "B0BJK5T1QR", "B0C7N1F4Y1", "B0F3CT8RFY", "B09Y9CYXK5", "B0BT7FB4MC",
    "B0DC52J7YZ", "B0D5D41L6R", "B09YXT3C1L", "B0B292NNQ1", "B0DFM8Y65X",
    "B095PLTKFV", "B09YXMVQTV", "B074L4MZRY", "B0DC53P9XX", "B0DC52TQSJ",
]

# Shared list for the four EU marketplaces (DE, FR, IT, ES).
_EU_ASINS = [
    "B07K1WBH4K","B07MD4LB49","B0BJK5GPRD","B0C8ZDBRGG","B0D5D41L6R",
    "B0DYP3S2Q7","B0BJK451HH","B0B5ZNJM36","B00VG5QV2O","B0BT7H247Z",
    "B00VFYPIDO","B0C7N1F4Y1","B0BJK5T3Z9","B0BJL537F1","B00R65SD4C",
    "B00VFYPK82","B0BF5KQFYV","B015J3FXOU","B0FSDLB9N4","B0757M47FW",
    "B07RDK9WTN","B0FP5QDGFV","B0B5285BRC","B0DYP54XFC","B0BJK33PFP",
    "B07MNSZ61S","B0C8ST8KVL","B0BJK93HN2","B0BV2YFWQR","B08G8SDB6D",
    "B0B528DFWL","B00VIDX8V6","B0186XTAUI","B0B5277MXT","B019FLGKZI",
    "B00VFYPG1S","B01JAK7UAS","B0B527SRQ9","B0DK5JHV4Q","B01M0DB0Z3",
    "B0BV2Z423K","B00Q6FM6GY","B017P6DS5A","B0BV2ZBJP8","B01K78VZE4",
    "B0BJK687Z2","B0B5277PX7","B0F5W48J88","B00XL1E6QO","B00M56WWX0",
    "B0D54CSMKV","B0BV323L3X","B00VBUY3SS","B07MNSWD6D","B0DBL9384Q",
    "B00VK0LF0S","B00QRVGUNW","B016IJ0YY8","B0757N4D53","B0BYK1F7Q8",
    "B07RLM88NM","B013P6ZFHI","B0B52MMLFP","B07RHN9RVP","B0D54DF9WQ",
    "B07M61PL9K","B0BV2Y41QJ","B00MN668VY","B00Q6UN3ZM","B0B52B1L1R",
    "B093663R1Q","B08G2LFLCG","B097HLWC93","B00M5A28YO","B0BJK4KWW2",
    "B016IL75S4","B00ZUTOATI","B0B526KNN6","B00VIDY1GC","B07RKWCXMB",
    "B0BV2YWK27","B0BF5GCDBG","B07RGK4H2B","B075XQXSLM","B01NA9WRZF",
    "B0B5266XD2","B07RHN6RRX","B07RHN9TDF","B0CGTZXY9M","B01M27XFKM",
    "B078J3C15N","B08LVZV78R","B07RJRJC7V","B00VIDZ72Y","B07RBN3ZMJ",
    "B01DZOZJNA","B08G2J583H","B07R6MHNMB","B0757VW95S","B096QC2CC7",
    "B07K1XSGBK","B074L4MZRY","B0C9CJ8L3N","B016KQXYZA","B075XR382W",
    "B07ZB61GXF","B0DHCJ1HHR","B08FXWK7LT","B0F5VYH6VX","B09DW76XD4",
]

_CA_ASINS = [
    "B0B293XFM4","B0BB1LXSPN","B09YY78NFQ","B0BT7H247Z","B09Y9G1436",
    "B0B2928XNH","B096KZ74F1","B07K1WBH4K","B09Y9BGBTF","B0C7N1F4Y1",
    "B096KWR1PK","B0BCKFGKFQ","B09YY7BCZ3","B09YXT3C1L","B0BZCPMQ36",
    "B09PV23QJQ","B096KWCHG2","B0C9CJ8L3N","B0B5LPWSGH","B0BFHKDK88",
    "B0BYHYKHG8","B0C7454VNB","B09Y9DYSD6","B00R65SD4C","B09PV289KH",
    "B096KTV5QP","B09Y9CJZZH","B0B292NNQ1","B09YXMVQTV","B07MD4LB49",
    "B0CZDFS4XX","B09Y9BJVJR","B01M0DB0Z3","B0757VW95S","B09Y9DJ6DW",
    "B09Y9CYXK5","B0BT7FB4MC","B09K45YFYL","B00Q6FM6GY","B0CZRZM97M",
    "B0F5VQN2NR","B0F5W48J88","B01JAK7UAS","B09K45HC68","B09YXKXY4N",
    "B0BCKGS74K","B09Y9DWNPZ","B09R1PSLYW","B09Y9D4WJQ","B09PLDGY6J",
    "B00VLOCBHE","B00VG5QV2O","B074L4MZRY","B01K78VZE4","B00XL1E6QO",
    "B01J3F13O4","B075XQXSLM","B096KXXFY6","B01MG3L67M","B01J3G9C5U",
    "B00S0NYCCG","B09K461LQL","B00ZUTOATI","B013P6ZFHI","B09K453RMM",
    "B00M56WWX0","B00VK0LF0S","B0757QHYVK","B09PV561PB","B09PV32JKR",
    "B01M7RQOE5","B07K1XSGBK","B0DK5JHV4Q","B07583WVRF","B0757M47FW",
    "B075XRJB6S","B0FP5QDGFV","B013P9H1AY","B0FSDLB9N4","B0FQ5V77LR",
    "B0FVFVZVLX","B0FMY2XW2Y",
]

PRICE_TRACKER_ASINS = {
    "UK": _UK_ASINS,
    "DE": _EU_ASINS,
    "FR": _EU_ASINS,
    "IT": _EU_ASINS,
    "ES": _EU_ASINS,
    "CA": _CA_ASINS,
}


def keepa_available():
    try:
        return "keepa" in st.secrets and bool(st.secrets["keepa"].get("api_key"))
    except Exception:
        return False


def _keepa_decode_csv(csv_arr, divide_by=100):
    """Decode a Keepa CSV array (alternating [keepa_minute, value, ...]).

    Returns list of (datetime, price) tuples. -1 values mean 'out of stock' /
    no data and are skipped. Keepa time = unix minutes since 2011-01-01.
    """
    import datetime as _d
    if not csv_arr:
        return []
    KEEPA_EPOCH = _d.datetime(2011, 1, 1)
    out = []
    for i in range(0, len(csv_arr) - 1, 2):
        km = csv_arr[i]
        val = csv_arr[i + 1]
        if val is None or val < 0:
            continue
        dt = KEEPA_EPOCH + _d.timedelta(minutes=int(km))
        out.append((dt, float(val) / divide_by))
    return out


def _last_raw_value(csv_arr):
    """Return the last value in a Keepa csv array (alternating time,value).
    Returns None if array is None/empty, otherwise the last value (may be -1)."""
    if not csv_arr or len(csv_arr) < 2: return None
    return csv_arr[-1]


@st.cache_data(ttl=86400, show_spinner=False)  # 24-hour cache
def _fetch_keepa_chunk(asins_tuple, domain_code):
    """Internal: fetch ONE chunk (≤50 ASINs) from Keepa. Cached per chunk."""
    if not keepa_available():
        return {"_error": "Keepa API key not configured in secrets.toml"}
    try:
        import urllib.request, urllib.error, urllib.parse, json, gzip, io
        api_key = st.secrets["keepa"]["api_key"]
        asins_csv = ",".join(asins_tuple)
        params = urllib.parse.urlencode({
            "key": api_key, "domain": domain_code,
            "asin": asins_csv, "stats": 90, "history": 1,
        })
        url = f"https://api.keepa.com/product?{params}"
        req = urllib.request.Request(url, headers={
            "User-Agent": "vahdam-dashboard",
            "Accept-Encoding": "gzip, deflate",
        })
        with urllib.request.urlopen(req, timeout=45) as r:
            raw = r.read()
            enc = (r.headers.get("Content-Encoding") or "").lower()
        # Decompress if needed — Keepa often returns gzip
        if enc == "gzip" or raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        elif enc == "deflate":
            import zlib
            try:
                raw = zlib.decompress(raw)
            except zlib.error:
                raw = zlib.decompress(raw, -zlib.MAX_WBITS)
        payload = json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="ignore")[:200]
        except Exception:
            body = ""
        return {"_error": f"Keepa HTTP {e.code} {e.reason}: {body}"}
    except Exception as e:
        return {"_error": f"Keepa request failed: {type(e).__name__}: {e}"}

    out = {
        "_tokens_left": payload.get("tokensLeft"),
        "_refill_in":   payload.get("refillIn"),
        "_refill_rate": payload.get("refillRate"),
    }
    sym = KEEPA_SYMBOL.get(domain_code, "$")
    for prod in payload.get("products", []):
        asin = prod.get("asin")
        if not asin: continue
        csv_data = prod.get("csv") or []
        # CSV index reference:
        # 0=AMAZON, 1=NEW, 2=USED, 3=SALES (rank), 7=LIST_PRICE,
        # 18=BUY_BOX_SHIPPING (most reliable), 32=BUY_BOX (price-only)
        amazon_arr  = csv_data[0]  if len(csv_data) > 0  else None
        new_arr     = csv_data[1]  if len(csv_data) > 1  else None
        buybox_arr  = csv_data[18] if len(csv_data) > 18 else None
        buybox2_arr = csv_data[32] if len(csv_data) > 32 else None

        amazon_pts = _keepa_decode_csv(amazon_arr)
        new_pts    = _keepa_decode_csv(new_arr)
        buybox_pts = _keepa_decode_csv(buybox_arr) or _keepa_decode_csv(buybox2_arr)

        def _last(pts):
            return pts[-1][1] if pts else None

        # Buybox status: present if the LATEST raw csv[18] value is a valid price.
        # -1 = no buybox at that moment (suppressed / no offer winning).
        last_raw_18 = _last_raw_value(buybox_arr)
        last_raw_32 = _last_raw_value(buybox2_arr)
        if last_raw_18 is not None:
            buybox_present = last_raw_18 >= 0
        elif last_raw_32 is not None:
            buybox_present = last_raw_32 >= 0
        else:
            buybox_present = None  # unknown — no history

        out[asin] = {
            "title":          prod.get("title", asin),
            "currency":       sym,
            "amazon_pts":     amazon_pts,
            "new_pts":        new_pts,
            "buybox_pts":     buybox_pts,
            "last_amazon":    _last(amazon_pts),
            "last_new":       _last(new_pts),
            "last_buybox":    _last(buybox_pts),
            "buybox_present": buybox_present,
            "stats":          prod.get("stats", {}),
        }
    return out


def fetch_keepa_products(asins_tuple, domain_code, chunk_size=50):
    """Public wrapper: auto-chunks large ASIN lists into multiple cached calls.

    Keepa accepts up to ~100 ASINs per request, but 50 is a safer default that
    keeps URLs short and lets each chunk cache independently."""
    asins = list(asins_tuple)
    if not asins:
        return {}
    if len(asins) <= chunk_size:
        return _fetch_keepa_chunk(tuple(asins), domain_code)

    merged = {}
    for i in range(0, len(asins), chunk_size):
        chunk = tuple(asins[i:i + chunk_size])
        part = _fetch_keepa_chunk(chunk, domain_code)
        if "_error" in part and i == 0:
            # First chunk failed — bubble it up so the UI shows the error.
            return part
        # Keep the most recent meta from the last successful chunk
        for k, v in part.items():
            merged[k] = v
    return merged


def _detect_price_anomaly(pts, lookback_days=7, threshold_pct=15.0):
    """Detect a price anomaly in the last `lookback_days`.

    Returns dict with 'flag': bool, 'change_pct': float, 'last': float,
    'baseline': float, 'direction': 'up'|'down'|None.
    """
    if not pts or len(pts) < 2:
        return {"flag": False}
    import datetime as _d
    cutoff = _d.datetime.utcnow() - _d.timedelta(days=lookback_days)
    recent = [p for d, p in pts if d >= cutoff]
    older  = [p for d, p in pts if d <  cutoff]
    if not recent or not older:
        return {"flag": False}
    last = recent[-1]
    baseline = sum(older[-min(len(older), 30):]) / min(len(older), 30)
    if baseline == 0:
        return {"flag": False}
    change = (last - baseline) / baseline * 100
    return {
        "flag":       abs(change) >= threshold_pct,
        "change_pct": change,
        "last":       last,
        "baseline":   baseline,
        "direction":  "up" if change > 0 else "down",
    }


def render_price_tracker():
    """Price Tracker view: per-GEO tabs, Keepa price charts, anomaly highlights."""
    st.markdown('<div class="page-title">Price Tracker</div>',
                unsafe_allow_html=True)
    st.markdown(
        '<div class="page-sub">Keepa-tracked price history per ASIN '
        '&nbsp;&bull;&nbsp; flagged when last price deviates >15% from the '
        'prior 30-day average &nbsp;&bull;&nbsp; data refreshes every 24 h '
        '(use sidebar Refresh to force-update)</div>',
        unsafe_allow_html=True)

    if not keepa_available():
        st.warning(
            "🔑 No Keepa API key found. Add it to Streamlit Cloud Secrets:\n\n"
            "```toml\n[keepa]\napi_key = \"your_keepa_api_key\"\n```\n"
            "Get a key at https://keepa.com/#!api"
        )
        return

    geos = list(PRICE_TRACKER_ASINS.keys())
    if not geos:
        st.info("No ASINs configured. Add them to PRICE_TRACKER_ASINS in app.py.")
        return

    geo_tabs = st.tabs([f"🌍 {g}" for g in geos])
    for geo, tab in zip(geos, geo_tabs):
        with tab:
            asins = PRICE_TRACKER_ASINS[geo]
            domain = KEEPA_DOMAIN.get(geo, 1)
            st.caption(f"{len(asins)} ASIN{'s' if len(asins) != 1 else ''} "
                       f"on Amazon.{'co.uk' if geo=='UK' else 'com'} · "
                       f"Keepa domain {domain}")

            with st.spinner(f"Fetching Keepa data for {len(asins)} ASINs…"):
                data = fetch_keepa_products(tuple(asins), domain)

            if "_error" in data:
                st.error(data["_error"])
                continue

            # Token usage info
            tl = data.get("_tokens_left")
            if tl is not None:
                st.caption(f"🪙 Keepa tokens left: **{tl}** "
                           f"· refill rate: {data.get('_refill_rate', '?')}/min")

            # ── Buybox-missing summary at the very top ──
            missing_buybox = []
            not_found = []
            for asin in asins:
                if asin not in data:
                    not_found.append(asin)
                    continue
                bp = data[asin].get("buybox_present")
                if bp is False:
                    missing_buybox.append((asin, data[asin]))

            if missing_buybox or not_found:
                bits = []
                if missing_buybox:
                    bits.append(f"🛒 {len(missing_buybox)} ASIN"
                                f"{'s' if len(missing_buybox) != 1 else ''} "
                                f"without an active Buy Box")
                if not_found:
                    bits.append(f"🔍 {len(not_found)} ASIN"
                                f"{'s' if len(not_found) != 1 else ''} not "
                                f"found in Keepa response")
                st.markdown(
                    f'<div class="alerts-row">'
                    f'<div class="alert-banner alert-danger">'
                    f'{" · ".join(bits)}</div></div>',
                    unsafe_allow_html=True)
                with st.expander(
                    f"🛒 Buy Box / availability — show details",
                    expanded=bool(missing_buybox)):
                    if missing_buybox:
                        st.markdown(
                            "<div style='font-size:12.5px;color:#8b1a1a;"
                            "font-weight:700;margin-bottom:6px;'>"
                            "Buy Box currently suppressed / unavailable:</div>",
                            unsafe_allow_html=True)
                        for asin, d in missing_buybox:
                            last_seen = d.get("last_buybox")
                            seen_txt = (f"last seen {d['currency']}{last_seen:.2f}"
                                        if last_seen else "no recent history")
                            st.markdown(
                                f"<div style='padding:4px 0;"
                                f"border-bottom:1px dashed #ede4d0;'>"
                                f"<b>{asin}</b> &nbsp;·&nbsp; "
                                f"<span class='small-muted'>{seen_txt}</span><br>"
                                f"<span style='font-size:11.5px;color:#7a6a50;'>"
                                f"{(d['title'] or '')[:80]}</span></div>",
                                unsafe_allow_html=True)
                    if not_found:
                        st.markdown(
                            "<div style='font-size:12.5px;color:#8b1a1a;"
                            "font-weight:700;margin:8px 0 4px 0;'>"
                            "Not in Keepa response (may not be live on this "
                            "marketplace):</div>",
                            unsafe_allow_html=True)
                        st.code(", ".join(not_found), language=None)

            # ── Anomaly summary ──
            anomalies = []
            for asin in asins:
                if asin not in data: continue
                d = data[asin]
                a = _detect_price_anomaly(d["amazon_pts"]) \
                    if d.get("amazon_pts") else _detect_price_anomaly(d["new_pts"])
                if a.get("flag"):
                    anomalies.append((asin, d, a))

            if anomalies:
                st.markdown(
                    f'<div class="alerts-row">'
                    f'<div class="alert-banner alert-warn">⚠️ {len(anomalies)} '
                    f'price {"anomaly" if len(anomalies) == 1 else "anomalies"} '
                    f'in the last 7 days — review below.</div></div>',
                    unsafe_allow_html=True)
                with st.expander(f"⚠️ {len(anomalies)} anomalies — show details",
                                 expanded=True):
                    for asin, d, a in anomalies:
                        arrow = "▲" if a["direction"] == "up" else "▼"
                        color = "#1a7a3e" if a["direction"] == "up" else "#8b1a1a"
                        title = d['title'][:70]
                        st.markdown(
                            f"<div style='padding:6px 0;border-bottom:1px dashed #ede4d0;'>"
                            f"<b>{asin}</b> &nbsp;·&nbsp; "
                            f"<span style='color:{color};font-weight:700;'>"
                            f"{arrow} {abs(a['change_pct']):.1f}%</span> "
                            f"&nbsp;<span class='small-muted'>"
                            f"{d['currency']}{a['baseline']:.2f} → "
                            f"{d['currency']}{a['last']:.2f}</span><br>"
                            f"<span style='font-size:11.5px;color:#7a6a50;'>"
                            f"{title}</span></div>",
                            unsafe_allow_html=True)
            else:
                st.success("✓ No price anomalies detected in the last 7 days.")

            # ── Per-ASIN price charts (3 per row) ──
            st.markdown('<div class="section-hdr" style="margin-top:18px;">'
                        'Price history (Amazon + New offer)</div>',
                        unsafe_allow_html=True)

            ROW = 3
            for row_start in range(0, len(asins), ROW):
                cols = st.columns(ROW, gap="medium")
                for i, asin in enumerate(asins[row_start:row_start + ROW]):
                    with cols[i]:
                        if asin not in data:
                            st.markdown(
                                f"<div class='pnl-strip' style='height:auto;'>"
                                f"<div class='pnl-strip-label'>{asin}</div>"
                                f"<div style='color:#8b1a1a;font-size:11px;'>"
                                f"Not found in Keepa response</div></div>",
                                unsafe_allow_html=True)
                            continue
                        d = data[asin]
                        title_short = (d["title"][:55] + "…") \
                            if len(d["title"]) > 55 else d["title"]

                        # Price header
                        last = d.get("last_amazon") or d.get("last_new") or d.get("last_buybox")
                        last_label = ("Amazon" if d.get("last_amazon")
                                      else "New" if d.get("last_new")
                                      else "Buy Box" if d.get("last_buybox")
                                      else "—")
                        last_str = f"{d['currency']}{last:.2f}" if last else "—"
                        anomaly = _detect_price_anomaly(
                            d["amazon_pts"] or d["new_pts"])
                        bb_missing = d.get("buybox_present") is False
                        if bb_missing:
                            bord = "#8b1a1a"
                        elif anomaly.get("flag"):
                            bord = "#AB8743"
                        else:
                            bord = "#d6ccba"
                        flag_html = ""
                        if bb_missing:
                            flag_html = ("<span style='color:#8b1a1a;font-weight:700;"
                                         "font-size:11px;'>🛒 No Buy Box</span>")
                        elif anomaly.get("flag"):
                            arrow = "▲" if anomaly["direction"] == "up" else "▼"
                            clr = "#1a7a3e" if anomaly["direction"] == "up" else "#8b1a1a"
                            flag_html = (f"<span style='color:{clr};font-weight:700;"
                                          f"font-size:11px;'>{arrow} "
                                          f"{abs(anomaly['change_pct']):.1f}%</span>")
                        st.markdown(
                            f"<div style='background:#fff;border:1px solid {bord};"
                            f"border-radius:8px;padding:8px 12px;"
                            f"margin-bottom:4px;'>"
                            f"<div style='font-size:11px;color:#AB8743;"
                            f"font-weight:700;letter-spacing:0.4px;'>{asin}</div>"
                            f"<div style='font-size:18px;font-weight:700;"
                            f"color:#004A2B;'>{last_str} "
                            f"<span class='small-muted' style='font-size:10px;"
                            f"font-weight:500;'>{last_label}</span> "
                            f"{flag_html}</div>"
                            f"<div style='font-size:10.5px;color:#7a6a50;"
                            f"line-height:1.3;'>{title_short}</div>"
                            f"</div>", unsafe_allow_html=True)

                        # Mini Plotly chart
                        if HAS_PLOTLY and (d["amazon_pts"] or d["new_pts"]):
                            fig = go.Figure()
                            if d["amazon_pts"]:
                                xs, ys = zip(*d["amazon_pts"])
                                fig.add_trace(go.Scatter(
                                    x=xs, y=ys, mode="lines",
                                    name="Amazon",
                                    line=dict(color="#004A2B", width=1.6),
                                    hovertemplate=(f"<b>%{{x|%d %b %Y}}</b><br>"
                                                   f"Amazon: {d['currency']}%{{y:.2f}}"
                                                   "<extra></extra>")))
                            if d["new_pts"]:
                                xs, ys = zip(*d["new_pts"])
                                fig.add_trace(go.Scatter(
                                    x=xs, y=ys, mode="lines",
                                    name="New",
                                    line=dict(color="#AB8743", width=1.2,
                                              dash="dot"),
                                    hovertemplate=(f"<b>%{{x|%d %b %Y}}</b><br>"
                                                   f"New: {d['currency']}%{{y:.2f}}"
                                                   "<extra></extra>")))
                            fig.update_layout(
                                plot_bgcolor="#FBF5EA", paper_bgcolor="#FBF5EA",
                                height=140,
                                margin=dict(l=10, r=10, t=6, b=20),
                                showlegend=False,
                                hovermode="x",
                                hoverlabel=dict(bgcolor="#ffffff",
                                                bordercolor="#004A2B",
                                                font=dict(size=11, color="#171717")),
                            )
                            fig.update_xaxes(showgrid=False,
                                              tickfont=dict(size=9, color="#7a6a50"),
                                              nticks=4)
                            fig.update_yaxes(showgrid=True,
                                              gridcolor="rgba(171,135,67,0.15)",
                                              tickfont=dict(size=9, color="#7a6a50"),
                                              tickprefix=d["currency"],
                                              nticks=4)
                            st.plotly_chart(fig, use_container_width=True,
                                            config={"displayModeBar": False})
                        else:
                            st.caption("No history available")


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

    where    = build_where()
    where_lm = build_where(date_from=lm_d_from, date_to=lm_d_to)

    # ── Summary KPI strip ──
    with st.spinner("Loading summary…"):
        _agg    = get_pnl_agg(where,    sfx)
        _agg_lm = get_pnl_agg(where_lm, sfx)

    if not _agg.empty:
        _r  = {k.upper(): v for k, v in _agg.iloc[0].items()}
        _rl = ({k.upper(): v for k, v in _agg_lm.iloc[0].items()}
               if not _agg_lm.empty else None)

        sales_act = _f(_r.get("SALES_ACT"));  sales_bud = _f(_r.get("SALES_BUD"))
        cm1_act   = _f(_r.get("CM1_ACT"));    cm1_bud   = _f(_r.get("CM1_BUD"))
        cm2_act   = _f(_r.get("CM2_ACT"));    cm2_bud   = _f(_r.get("CM2_BUD"))
        pm_act    = _f(_r.get("PM_SPEND_ACT"));pm_bud   = _f(_r.get("PM_SPEND_BUD"))

        def _ratio(a, b):
            a, b = _f(a), _f(b)
            if a is None or b is None or b == 0: return None
            return a / b * 100

        def _pct_change(cur, prev_key):
            if _rl is None: return None
            c, p = _f(cur), _f(_rl.get(prev_key))
            if c is None or p is None or p == 0: return None
            return (c - p) / abs(p) * 100

        # Sales — absolute Rev vs Bud
        c0 = strip_card("Sales", fmt_lakhs(sales_act),
                        f"Bud: {fmt_lakhs(sales_bud)}",
                        delta=_pct_change(sales_act, "SALES_ACT"),
                        vs_b_pct=_ratio(sales_act, sales_bud))
        # CM1 Margin % — ratio of actual margin vs budget margin
        cm1_pct = _ratio(cm1_act, sales_act)
        cm1_bud_pct = _ratio(cm1_bud, sales_bud)
        cm1_pct_lm = (_ratio(_f(_rl.get("CM1_ACT")) if _rl else None,
                              _f(_rl.get("SALES_ACT")) if _rl else None))
        c1 = strip_card("CM1 Margin", fmt_pct(cm1_pct),
                        f"Bud: {fmt_pct(cm1_bud_pct)}",
                        delta=(_pct_change(cm1_pct, "_dummy") if False else
                               ((cm1_pct - cm1_pct_lm) / abs(cm1_pct_lm) * 100
                                if (cm1_pct is not None and cm1_pct_lm not in (None, 0)) else None)),
                        vs_b_pct=_ratio(cm1_pct, cm1_bud_pct))
        # CM2 Margin %
        cm2_pct = _ratio(cm2_act, sales_act)
        cm2_bud_pct = _ratio(cm2_bud, sales_bud)
        cm2_pct_lm = (_ratio(_f(_rl.get("CM2_ACT")) if _rl else None,
                              _f(_rl.get("SALES_ACT")) if _rl else None))
        c2 = strip_card("CM2 Margin", fmt_pct(cm2_pct),
                        f"Bud: {fmt_pct(cm2_bud_pct)}",
                        delta=((cm2_pct - cm2_pct_lm) / abs(cm2_pct_lm) * 100
                               if (cm2_pct is not None and cm2_pct_lm not in (None, 0)) else None),
                        vs_b_pct=_ratio(cm2_pct, cm2_bud_pct))
        # PM Spend — absolute (lower vs budget = good)
        c3 = strip_card("PM Spend", fmt_lakhs(pm_act),
                        f"Bud: {fmt_lakhs(pm_bud)}",
                        delta=_pct_change(pm_act, "PM_SPEND_ACT"),
                        vs_b_pct=_ratio(pm_act, pm_bud), vs_b_lower_better=True)
        # CM2 Absolute (replaces "Rev vs Bud" with a more useful metric)
        c4 = strip_card("CM2 Absolute", fmt_lakhs(cm2_act),
                        f"Bud: {fmt_lakhs(cm2_bud)}",
                        delta=_pct_change(cm2_act, "CM2_ACT"),
                        vs_b_pct=_ratio(cm2_act, cm2_bud))

        scols = st.columns(5, gap="medium")
        for col, html in zip(scols, [c0, c1, c2, c3, c4]):
            col.markdown(html, unsafe_allow_html=True)
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
elif view == "asin_detail":
    render_asin_detail()
elif view == "pnl":
    render_pnl()
elif view == "price":
    render_price_tracker()
else:
    render_asin()
