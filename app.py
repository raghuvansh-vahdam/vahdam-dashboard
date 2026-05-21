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
        /* `min-height` (not fixed height) — the Exec Summary cards now carry
           two delta lines (vs LM + vs LY) each with a raw value in parens, so
           the card must be free to grow. */
        min-height: 138px; height: auto;
        display: flex; flex-direction: column;
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
    /* Only the FIRST .kpi-delta acts as a flex spacer (pushes the comparison
       block to the bottom). Any subsequent delta (e.g. "vs LY") then stacks
       directly below it instead of being yanked back to the bottom too. */
    .pnl-strip .kpi-delta { font-size: 11px; line-height: 1.3; }
    .pnl-strip .kpi-delta:first-of-type { margin-top: auto; }
    .pnl-strip .kpi-delta + .kpi-delta  { margin-top: 2px; }
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

    /* ── Customer Insights cards ── */
    .ci-card {
        background: #ffffff; border: 1px solid #e8dfc9;
        border-left: 4px solid #d6ccba; border-radius: 10px;
        padding: 12px 14px 11px 14px; margin-bottom: 10px;
        box-shadow: 0 1px 3px rgba(0,74,43,0.05);
        transition: transform .12s ease, box-shadow .12s ease,
                    border-color .12s ease;
    }
    .ci-card:hover {
        transform: translateY(-1px);
        box-shadow: 0 4px 10px rgba(0,74,43,0.10);
    }
    .ci-card.ci-fix    { border-left-color: #8b1a1a; }
    .ci-card.ci-watch  { border-left-color: #c75c3c; }
    .ci-card.ci-amber  { border-left-color: #AB8743; }
    .ci-card.ci-win    { border-left-color: #1a7a3e; }
    .ci-card-head {
        display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
        margin-bottom: 4px;
    }
    .ci-badge {
        display: inline-flex; align-items: center;
        font-size: 9.5px; font-weight: 800; letter-spacing: 0.8px;
        padding: 2px 8px; border-radius: 999px;
        text-transform: uppercase;
    }
    .ci-title {
        font-size: 13px; font-weight: 700; color: #004A2B;
        line-height: 1.25; flex: 1 1 auto;
    }
    .ci-title .ci-asin {
        font-weight: 500; color: #7a6a50; font-size: 11.5px;
    }
    .ci-stats {
        font-size: 11.5px; color: #5a4d35; margin: 2px 0 6px 0;
        line-height: 1.4;
    }
    .ci-stats b { color: #004A2B; }
    .ci-themes {
        display: flex; flex-wrap: wrap; gap: 4px; margin: 4px 0 6px 0;
    }
    .ci-chip {
        display: inline-flex; align-items: center; gap: 4px;
        font-size: 10.5px; font-weight: 600; padding: 2px 8px;
        border-radius: 999px; border: 1px solid;
    }
    .ci-chip-neg { background: #fde8e8; color: #8b1a1a; border-color: #f0c5c5; }
    .ci-chip-pos { background: #d6ece1; color: #004A2B; border-color: #bcd9c8; }
    .ci-chip-count { font-weight: 700; opacity: .85; }
    .ci-quote {
        font-size: 11.5px; color: #5a4d35; font-style: italic;
        padding: 6px 10px; background: #faf5ea; border-radius: 6px;
        border-left: 2px solid #d6ccba; line-height: 1.4;
        margin-top: 6px;
    }
    .ci-quote::before { content: '"'; color: #AB8743; font-weight: 700;
                         margin-right: 2px; }
    .ci-quote::after  { content: '"'; color: #AB8743; font-weight: 700;
                         margin-left: 2px; }
    .ci-empty {
        text-align: center; padding: 20px; color: #7a6a50;
        font-size: 12.5px; font-style: italic;
    }

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
TABLE          = "vahdam_db.maplemonk.vahdam_amazon_pnl_overall_fy27_onwards"
MKTG           = "vahdam_db.maplemonk.VAHDAM_AMAZON_MARKETING"
SALES_MKT      = "vahdam_db.maplemonk.VAHDAM_AMAZON_SALES_MARKETING"
INV_3P         = "vahdam_db.maplemonk.vahdam_amazon_3P_inv"
REVIEWS        = "vahdam_db.maplemonk.Amazon_reviews_detailed_reviews"
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
    if st.button("Customer Insights", use_container_width=True, key="nav_ci"):
        st.session_state.view = "customer_insights"
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

def fmt_units(v, signed=False):
    """Auto-scale a unit count: <1K → raw int, <1L → K, <1Cr → L, ≥1Cr → Cr.
    Same shape as fmt_lakhs but no currency symbol — for Units / Quantity."""
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
        return f"{sign}{a:,.0f}"
    if scaled >= 100:
        return f"{sign}{scaled:,.0f}{unit}"
    if scaled >= 10:
        return f"{sign}{scaled:,.1f}{unit}"
    return f"{sign}{scaled:,.2f}{unit}"

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
            ROUND((SUM(CM2_ACTUAL_{sfx})-SUM(CM2_BUDGET_{sfx}))/NULLIF(ABS(SUM(CM2_BUDGET_{sfx})),0)*100,1) AS CM2_ABS_DELTA,
            COALESCE(SUM(QTY_ACTUAL),0)                                                   AS UNITS_ACT,
            COALESCE(SUM(QTY_BUDGET),0)                                                   AS UNITS_BUD,
            ROUND(SUM(QTY_ACTUAL)/NULLIF(SUM(QTY_BUDGET),0)*100,1)                        AS UNITS_PCT
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
            ROUND(SUM(CM2_ACTUAL_{sfx})/NULLIF(SUM(CM2_BUDGET_{sfx}),0)*100,1) AS CM2_ABS_ACHVD_PCT,
            COALESCE(SUM(QTY_BUDGET),0)       AS UNITS_BUD,
            COALESCE(SUM(QTY_ACTUAL),0)       AS UNITS_ACT
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
            ROUND(SUM(CM2_ACTUAL_{sfx})/NULLIF(SUM(CM2_BUDGET_{sfx}),0)*100,1),
            COALESCE(SUM(QTY_BUDGET),0),
            COALESCE(SUM(QTY_ACTUAL),0)
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
    separately to avoid join row-multiplication, then merged in pandas.
    Both tables use SPLIT_PART on ASIN so trailing suffixes never silently
    drop rows."""
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
          AND SPLIT_PART(ASIN,' ',1) = '{a}'
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


@st.cache_data(ttl=3600)
def discover_sales_mkt_cols():
    """Return uppercased column names of VAHDAM_AMAZON_SALES_MARKETING.
    Cached for 1 hour; returns empty frozenset if the table is unavailable."""
    try:
        df = run_query("""
            SELECT UPPER(COLUMN_NAME) AS COL
            FROM information_schema.columns
            WHERE UPPER(TABLE_CATALOG) = 'VAHDAM_DB'
              AND UPPER(TABLE_SCHEMA)  = 'MAPLEMONK'
              AND UPPER(TABLE_NAME)    = 'VAHDAM_AMAZON_SALES_MARKETING'
        """)
        return frozenset(df["COL"].tolist())
    except Exception:
        return frozenset()


def _sales_mkt_col(*candidates):
    """Pick the first column name that actually exists in the sales-mkt
    table from a list of likely candidates. Returns None if none exist."""
    cols = discover_sales_mkt_cols()
    for c in candidates:
        if c.upper() in cols:
            return c
    return None


@st.cache_data(ttl=300, show_spinner=False)
def get_asin_rolling(asin, geo, sfx):
    """Fetch the LAST 90 DAYS of (units, revenue, spend, sessions) for one
    ASIN, regardless of the user-selected window. Used to build the
    rolling 7 / 30 / 90 day cards so they are always accurate even when
    the user picked a short window. Returns one row per day with columns
    DAY, REVENUE, UNITS, SPEND, SESSIONS. Sessions come from
    vahdam_amazon_sales_marketing — the sessions column name is discovered
    dynamically and the column degrades gracefully to 0 if missing."""
    today_ = date.today()
    d_start = today_ - timedelta(days=89)
    a = asin.replace("'", "''")

    pnl = run_query(f"""
        SELECT DAY,
            COALESCE(ROUND(SUM(SALES_ACTUAL_{sfx}),0),0)  AS REVENUE,
            COALESCE(SUM(QTY_ACTUAL),0)                   AS UNITS
        FROM {TABLE}
        WHERE DAY BETWEEN '{d_start}' AND '{today_}'
          AND GEO = '{geo}' AND {GEO_EXCL}
          AND SPLIT_PART(ASIN,' ',1) = '{a}'
        GROUP BY DAY
    """)
    mkt = run_query(f"""
        SELECT DAY,
            COALESCE(ROUND(SUM(SPEND),0),0)  AS SPEND
        FROM {MKTG}
        WHERE DAY BETWEEN '{d_start}' AND '{today_}'
          AND GEO = '{geo}'
          AND SPLIT_PART(ASIN,' ',1) = '{a}'
        GROUP BY DAY
    """)

    # SESSIONS pull: probe likely column names so the dashboard works
    # whether the column is SESSIONS, SESSIONS_TOTAL, BROWSER_SESSIONS, etc.
    sess_col = _sales_mkt_col(
        "SESSIONS", "SESSIONS_TOTAL", "BROWSER_SESSIONS",
        "TOTAL_SESSIONS", "SESSIONS_B2C", "ORDERED_SESSIONS",
    )
    sm = pd.DataFrame(columns=["DAY", "SESSIONS"])
    if sess_col:
        try:
            sm = run_query(f"""
                SELECT DAY,
                    COALESCE(SUM({sess_col}),0) AS SESSIONS
                FROM {SALES_MKT}
                WHERE DAY BETWEEN '{d_start}' AND '{today_}'
                  AND GEO = '{geo}'
                  AND SPLIT_PART(ASIN,' ',1) = '{a}'
                GROUP BY DAY
            """)
        except Exception:
            sm = pd.DataFrame(columns=["DAY", "SESSIONS"])

    for df_ in (pnl, mkt, sm):
        if not df_.empty:
            df_["DAY"] = pd.to_datetime(df_["DAY"])

    if pnl.empty and mkt.empty and sm.empty:
        return pd.DataFrame(columns=["DAY","REVENUE","UNITS","SPEND","SESSIONS"])

    merged = pnl if not pnl.empty else pd.DataFrame(columns=["DAY"])
    for df_ in (mkt, sm):
        if not df_.empty:
            merged = pd.merge(merged, df_, on="DAY", how="outer")
    for c in ["REVENUE", "UNITS", "SPEND", "SESSIONS"]:
        if c not in merged.columns:
            merged[c] = 0
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
    """ASIN-level table for the ASIN view.

    IMPORTANT: P&L and marketing MUST be aggregated separately before any
    join, otherwise a single (day, ASIN) row in the P&L table gets duplicated
    by the number of campaign rows in the marketing table — which inflates
    revenue, units, CM1, CM2 and spend at the ASIN level (subcategory totals
    looked correct because get_asin_totals already aggregates separately).

    Inventory + cover-days columns:
      * FBA / ADW snapshot read from vahdam_amazon_3P_inv (latest day,
        with the header-pollution row "DATE='Date'" filtered out).
      * Total Inv = FBA only for non-USA marketplaces (UK, CA, DE, …).
      * Total Inv = FBA + ADW for USA.
      * Cover Days = Total Inv ÷ max daily run-rate across 3 windows
        (last 7d, last 14d, last 30d). The max picks the most aggressive
        recent velocity so cover days stay conservative. Yesterday alone
        is intentionally NOT in the mix — a single-day spike (e.g. a
        coupon drop) should not collapse the cover-days estimate.
    """
    esc = sub_cat.replace("'","''")
    if sub_cat == "(untagged)":
        pnl_subcat = "COALESCE(NULLIF(SUB_CATEGORY,''),'(untagged)') = '(untagged)'"
    else:
        pnl_subcat = f"UPPER(TRIM(COALESCE(SUB_CATEGORY,''))) = UPPER(TRIM('{esc}'))"

    today_ = date.today()
    d_30 = today_ - timedelta(days=29)   # inclusive 30-day window
    d_14 = today_ - timedelta(days=13)
    d_7  = today_ - timedelta(days=6)

    is_usa = (geo or "").upper() == "USA"
    total_inv_expr = (
        "(COALESCE(i.FBA_INV,0) + COALESCE(i.ADW_INV,0))" if is_usa
        else "COALESCE(i.FBA_INV,0)"
    )

    return run_query(f"""
        WITH pnl AS (
            SELECT
                SPLIT_PART(ASIN,' ',1)                                  AS ASIN_KEY,
                MAX(COALESCE(NULLIF(COMMON_SKU_DESCRIPTION,''), ASIN))  AS PRODUCT_NAME,
                MAX(BRAND)                                              AS BRAND,
                MAX(CHANNEL)                                            AS CHANNEL,
                SUM(QTY_BUDGET)                                         AS BUD_UNITS_RAW,
                SUM(SALES_BUDGET_{sfx})                                 AS BUD_REVENUE_RAW,
                SUM(CM1_BUDGET_{sfx})                                   AS CM1_BUD_RAW,
                SUM(PM_SPEND_BUDGET_{sfx})                              AS PM_SPEND_BUD_RAW,
                SUM(CM2_BUDGET_{sfx})                                   AS CM2_BUD_RAW,
                SUM(QTY_ACTUAL)                                         AS ACT_UNITS_RAW,
                SUM(SALES_ACTUAL_{sfx})                                 AS ACT_REVENUE_RAW,
                SUM(CM1_ACTUAL_{sfx})                                   AS CM1_ACT_RAW,
                SUM(PM_SPEND_ACTUAL_{sfx})                              AS PM_SPEND_ACT_RAW,
                SUM(CM2_ACTUAL_{sfx})                                   AS CM2_ACT_RAW
            FROM {TABLE}
            WHERE DAY BETWEEN '{d_from}' AND '{d_to}'
              AND GEO = '{geo}' AND {GEO_EXCL}
              AND {pnl_subcat}
              AND ASIN IS NOT NULL AND ASIN != ''
            GROUP BY SPLIT_PART(ASIN,' ',1)
        ),
        mkt AS (
            SELECT
                SPLIT_PART(ASIN,' ',1)  AS ASIN_KEY,
                SUM(SPEND)              AS PAID_SPEND_RAW,
                SUM(AD_SALES)           AS PAID_REVENUE_RAW,
                SUM(IMPRESSIONS)        AS IMPRESSIONS_RAW,
                SUM(CLICKS)             AS CLICKS_RAW,
                SUM(CONVERSIONS)        AS PAID_UNITS_RAW
            FROM {MKTG}
            WHERE DAY BETWEEN '{d_from}' AND '{d_to}'
              AND GEO = '{geo}'
              AND ASIN IS NOT NULL AND ASIN != ''
            GROUP BY SPLIT_PART(ASIN,' ',1)
        ),
        inv AS (
            -- Latest inventory snapshot. The source table is a per-day
            -- snapshot but only the most recent date is meaningful; we
            -- MAX over date to pick the freshest reading per ASIN and
            -- filter out the literal header-pollution row.
            SELECT
                UPPER(SPLIT_PART(ASIN, ' ', 1))  AS ASIN_KEY,
                MAX(FBAINV)                      AS FBA_INV,
                MAX(ADWINV)                      AS ADW_INV
            FROM {INV_3P}
            WHERE UPPER(GEO) = UPPER('{geo}')
              AND ASIN IS NOT NULL
              AND UPPER(ASIN) NOT IN ('ASIN', '')
              AND DATE <> 'Date'
            GROUP BY UPPER(SPLIT_PART(ASIN, ' ', 1))
        ),
        roll AS (
            -- Rolling unit-velocity windows (7d, 14d, 30d). We always pull
            -- the last 30 days here irrespective of the user-selected
            -- period, so cover-days are correct even when the page filter
            -- is shorter than 30 days. Yesterday-only is intentionally
            -- excluded — a single-day spike should not collapse cover.
            SELECT
                SPLIT_PART(ASIN,' ',1) AS ASIN_KEY,
                SUM(CASE WHEN DAY BETWEEN '{d_7}'  AND '{today_}' THEN COALESCE(QTY_ACTUAL,0) ELSE 0 END) AS U_7D,
                SUM(CASE WHEN DAY BETWEEN '{d_14}' AND '{today_}' THEN COALESCE(QTY_ACTUAL,0) ELSE 0 END) AS U_14D,
                SUM(CASE WHEN DAY BETWEEN '{d_30}' AND '{today_}' THEN COALESCE(QTY_ACTUAL,0) ELSE 0 END) AS U_30D
            FROM {TABLE}
            WHERE DAY BETWEEN '{d_30}' AND '{today_}'
              AND GEO = '{geo}' AND {GEO_EXCL}
              AND {pnl_subcat}
              AND ASIN IS NOT NULL AND ASIN != ''
            GROUP BY SPLIT_PART(ASIN,' ',1)
        )
        SELECT
            p.ASIN_KEY                                                              AS ASIN,
            p.PRODUCT_NAME                                                          AS PRODUCT_NAME,
            p.BRAND                                                                 AS BRAND,
            p.CHANNEL                                                               AS CHANNEL,
            -- Budget
            ROUND(p.BUD_UNITS_RAW, 0)                                               AS BUD_UNITS,
            ROUND(p.BUD_REVENUE_RAW, 0)                                             AS BUD_REVENUE,
            ROUND(p.BUD_REVENUE_RAW / NULLIF(p.BUD_UNITS_RAW, 0), 2)                AS BUD_ASP,
            ROUND(p.CM1_BUD_RAW / NULLIF(p.BUD_REVENUE_RAW, 0) * 100, 1)            AS BUD_CM1_PCT,
            ROUND(p.PM_SPEND_BUD_RAW / NULLIF(p.BUD_REVENUE_RAW, 0) * 100, 1)       AS BUD_ACOS_PCT,
            ROUND(p.CM2_BUD_RAW / NULLIF(p.BUD_REVENUE_RAW, 0) * 100, 1)            AS BUD_CM2_PCT,
            -- P&L Actuals
            ROUND(p.ACT_UNITS_RAW, 0)                                               AS ACT_UNITS,
            ROUND(p.ACT_REVENUE_RAW, 0)                                             AS ACT_REVENUE,
            ROUND(p.ACT_REVENUE_RAW / NULLIF(p.ACT_UNITS_RAW, 0), 2)                AS ACT_ASP,
            ROUND(p.CM1_ACT_RAW / NULLIF(p.ACT_REVENUE_RAW, 0) * 100, 1)            AS ACT_CM1_PCT,
            ROUND(p.PM_SPEND_ACT_RAW, 0)                                            AS ACT_SPEND,
            ROUND(p.PM_SPEND_ACT_RAW / NULLIF(p.ACT_REVENUE_RAW, 0) * 100, 1)       AS ACT_ACOS_PCT,
            ROUND(p.CM2_ACT_RAW / NULLIF(p.ACT_REVENUE_RAW, 0) * 100, 1)            AS ACT_CM2_PCT,
            ROUND(p.CM2_ACT_RAW, 0)                                                 AS ACT_CM2_ABS,
            ROUND(p.ACT_REVENUE_RAW / NULLIF(p.BUD_REVENUE_RAW, 0) * 100, 1)        AS REV_ACHVD_PCT,
            -- Marketing (paid ads) — null-safe when no ad rows exist
            COALESCE(ROUND(m.PAID_SPEND_RAW,    0), 0)                              AS PAID_SPEND,
            COALESCE(ROUND(m.PAID_REVENUE_RAW,  0), 0)                              AS PAID_REVENUE,
            COALESCE(ROUND(m.IMPRESSIONS_RAW,   0), 0)                              AS IMPRESSIONS,
            COALESCE(ROUND(m.CLICKS_RAW,        0), 0)                              AS CLICKS,
            COALESCE(ROUND(m.PAID_UNITS_RAW,    0), 0)                              AS PAID_UNITS,
            ROUND(m.CLICKS_RAW       / NULLIF(m.IMPRESSIONS_RAW, 0) * 100, 2)       AS CTR_PCT,
            ROUND(m.PAID_SPEND_RAW   / NULLIF(m.CLICKS_RAW,      0),       2)       AS CPC,
            ROUND(m.PAID_REVENUE_RAW / NULLIF(m.PAID_SPEND_RAW,  0),       2)       AS PACOS,
            ROUND(m.PAID_SPEND_RAW   / NULLIF(m.PAID_REVENUE_RAW,0) * 100, 1)       AS AD_ACOS_PCT,
            ROUND(m.PAID_REVENUE_RAW / NULLIF(p.ACT_REVENUE_RAW, 0) * 100, 1)       AS PCT_PAID_SALES,
            ROUND(m.PAID_UNITS_RAW   / NULLIF(m.CLICKS_RAW,      0) * 100, 2)       AS CONV_RATE_PCT,
            -- Inventory + cover days
            COALESCE(i.FBA_INV, 0)                                                  AS FBA_INV,
            COALESCE(i.ADW_INV, 0)                                                  AS ADW_INV,
            {total_inv_expr}                                                        AS TOTAL_INV,
            GREATEST(
                COALESCE(r.U_7D,  0) / 7.0,
                COALESCE(r.U_14D, 0) / 14.0,
                COALESCE(r.U_30D, 0) / 30.0
            )                                                                       AS DAILY_RUN_RATE,
            CASE
                WHEN GREATEST(
                    COALESCE(r.U_7D,  0) / 7.0,
                    COALESCE(r.U_14D, 0) / 14.0,
                    COALESCE(r.U_30D, 0) / 30.0
                ) > 0
                THEN ROUND({total_inv_expr}::FLOAT
                    / GREATEST(
                        COALESCE(r.U_7D,  0) / 7.0,
                        COALESCE(r.U_14D, 0) / 14.0,
                        COALESCE(r.U_30D, 0) / 30.0
                    ), 1)
                ELSE NULL
            END                                                                     AS COVER_DAYS
        FROM pnl p
        LEFT JOIN mkt  m ON p.ASIN_KEY = m.ASIN_KEY
        LEFT JOIN inv  i ON UPPER(p.ASIN_KEY) = i.ASIN_KEY
        LEFT JOIN roll r ON p.ASIN_KEY = r.ASIN_KEY
        WHERE COALESCE(p.ACT_REVENUE_RAW, 0) > 0
           OR COALESCE(m.PAID_SPEND_RAW,   0) > 0
        ORDER BY p.ACT_REVENUE_RAW DESC NULLS LAST
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
               vs_b_pct=None, vs_b_lower_better=False,
               lm_value=None, ly_delta=None, ly_value=None):
    """Compact KPI card matching the P&L summary strip style. Reusable across views.

    vs_b_pct: optional achievement % vs budget (e.g. 101.2 means 1.2% above plan).
              Renders a small pill between the sub line and the delta line.
    vs_b_lower_better: when True (e.g. for ad spend), <100% is good (green).

    Comparison lines (rendered under the vs-B pill, stacked):
      delta + delta_suffix  →  "▲ 0.4%  vs LM   (₹10.5Cr)"   if lm_value given
      ly_delta              →  "▲ 5.2%  vs LY   (₹9.50Cr)"   if ly_value given
    Both delta lines accept `None` and quietly drop out.
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

    def _delta_line(pct, suffix, raw_value):
        d = _f(pct)
        if d is None and raw_value is None:
            return ""
        cls = "delta-up" if (d is not None and d >= 0) else "delta-dn"
        arrow = "▲" if (d is not None and d >= 0) else "▼"
        pct_html = f"{arrow} {abs(d):.1f}%" if d is not None else "—"
        suffix_html = (f' <span class="small-muted" '
                       f'style="font-weight:500;">{suffix}</span>'
                       if suffix else "")
        val_html = (f' <span class="small-muted" '
                    f'style="font-weight:500;white-space:nowrap;">'
                    f'({raw_value})</span>'
                    if raw_value else "")
        return (f'<div class="kpi-delta {cls}">'
                f'{pct_html}{suffix_html}{val_html}</div>')

    delta_html  = _delta_line(delta,    delta_suffix, lm_value)
    delta_html += _delta_line(ly_delta, "vs LY",      ly_value)

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
    where_ly   = build_where(date_from=ly_d_from, date_to=ly_d_to)
    where_fm   = build_where(date_from=month_start, date_to=month_end)
    kpi        = get_kpis(where, sfx)
    kpi_lm     = get_kpis(where_lm, sfx)
    kpi_ly     = get_kpis(where_ly, sfx)
    kpi_fm     = get_kpis(where_fm, sfx)  # full-month budget for forecast
    df         = get_view1(where, sfx)

    if kpi.empty:
        st.warning("📭 No data found for the selected filters.")
        return
    k = kpi.iloc[0]
    klm = kpi_lm.iloc[0] if not kpi_lm.empty else None
    kly = kpi_ly.iloc[0] if not kpi_ly.empty else None
    kfm = kpi_fm.iloc[0] if not kpi_fm.empty else None

    # Narrative
    narrative = build_narrative(k, df if not df.empty else None)
    if narrative:
        st.markdown(f'<div class="narrative">📊 {narrative}</div>',
                    unsafe_allow_html=True)

    # ── 6 KPI cards: Revenue · Quantity · CM1% · ACoS% · CM2% · CM2 Abs ──
    def _ratio(act, bud):
        a, b = _f(act), _f(bud)
        if a is None or b is None or b == 0: return None
        return a / b * 100

    def _pct_change(cur, prev):
        c, p = _f(cur), _f(prev)
        if c is None or p is None or p == 0: return None
        return (c - p) / abs(p) * 100

    def _prev_val(prev_kpi, key):
        return prev_kpi.get(key) if prev_kpi is not None else None

    # Each card: (label, value, sub, lower-better, kpi_key, formatter)
    #   `lower-better` flips the vs-B pill direction (e.g. ACoS% lower is better)
    #   `formatter`     formats the raw LM / LY values shown in parentheses
    card_defs = [
        ("Revenue",  fmt_lakhs(k.get("SALES_ACT")),
            f"Bud: {fmt_lakhs(k.get('SALES_BUD'))}",
            False, "SALES_ACT",   fmt_lakhs,
            _ratio(k.get("SALES_ACT"),    k.get("SALES_BUD"))),
        ("Quantity", fmt_units(k.get("UNITS_ACT")),
            f"Bud: {fmt_units(k.get('UNITS_BUD'))}",
            False, "UNITS_ACT",   fmt_units,
            _ratio(k.get("UNITS_ACT"),    k.get("UNITS_BUD"))),
        ("CM1%",     fmt_pct(k.get("CM1_ACT")),
            f"Bud: {fmt_pct(k.get('CM1_BUD'))}",
            False, "CM1_ACT",     fmt_pct,
            _ratio(k.get("CM1_ACT"),      k.get("CM1_BUD"))),
        ("ACoS%",    fmt_pct(k.get("ACOS_ACT")),
            f"Bud: {fmt_pct(k.get('ACOS_BUD'))}",
            True,  "ACOS_ACT",    fmt_pct,
            _ratio(k.get("ACOS_ACT"),     k.get("ACOS_BUD"))),
        ("CM2%",     fmt_pct(k.get("CM2_ACT")),
            f"Bud: {fmt_pct(k.get('CM2_BUD'))}",
            False, "CM2_ACT",     fmt_pct,
            _ratio(k.get("CM2_ACT"),      k.get("CM2_BUD"))),
        ("CM2 Abs",  fmt_lakhs(k.get("CM2_ABS_ACT")),
            f"Bud: {fmt_lakhs(k.get('CM2_ABS_BUD'))}",
            False, "CM2_ABS_ACT", fmt_lakhs,
            _ratio(k.get("CM2_ABS_ACT"), k.get("CM2_ABS_BUD"))),
    ]
    cols = st.columns(6, gap="medium")
    for col, (lbl, val, sub, lb, key, fmt, ach) in zip(cols, card_defs):
        cur     = k.get(key)
        lm_raw  = _prev_val(klm, key)
        ly_raw  = _prev_val(kly, key)
        col.markdown(
            strip_card(
                lbl, val, sub,
                delta=_pct_change(cur, lm_raw),
                vs_b_pct=ach,
                vs_b_lower_better=lb,
                lm_value=fmt(lm_raw) if lm_raw is not None else None,
                ly_delta=_pct_change(cur, ly_raw),
                ly_value=fmt(ly_raw) if ly_raw is not None else None,
            ),
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
    # Lag(R) = Budget Rev − Actual Rev (positive when we're behind plan)
    # Lag(U) = Budget Units − Actual Units
    disp["_LAG_REV"]   = pd.to_numeric(disp["SALES_BUD"], errors="coerce") - \
                         pd.to_numeric(disp["SALES_ACT"], errors="coerce")
    disp["_LAG_UNITS"] = pd.to_numeric(disp["UNITS_BUD"], errors="coerce") - \
                         pd.to_numeric(disp["UNITS_ACT"], errors="coerce")
    disp["Budget Rev"]   = disp["SALES_BUD"].apply(fmt_lakhs)
    disp["Actual Rev"]   = disp["SALES_ACT"].apply(fmt_lakhs)
    # Lag(R) / Lag(U) are kept NUMERIC so the column header sort is
    # numeric. Display formatting comes from st.column_config below.
    disp["Lag(R)"]       = disp["_LAG_REV"]
    disp["Lag(U)"]       = disp["_LAG_UNITS"]
    disp["Budget CM1"]   = disp["CM1_BUD"].apply(fmt_lakhs)
    disp["Actual CM1"]   = disp["CM1_ACT"].apply(fmt_lakhs)
    disp["Act ACoS%"]    = disp["ACOS_PCT_ACT"].apply(fmt_pct)
    disp["Bud ACoS%"]    = disp["ACOS_PCT_BUD"].apply(fmt_pct)
    disp["Budget CM2"]   = disp["CM2_BUD"].apply(fmt_lakhs)
    disp["Actual CM2"]   = disp["CM2_ACT"].apply(fmt_lakhs)
    disp["Act CM2%"]     = disp["CM2_PCT_ACT"].apply(fmt_pct)
    disp["Bud CM2%"]     = disp["CM2_PCT_BUD"].apply(fmt_pct)
    disp["% Achieved"]   = disp["REV_PCT"].apply(fmt_pct)
    disp["CM2 Abs %"]    = disp["CM2_ABS_ACHVD_PCT"].apply(fmt_pct)
    disp["CM2 Var"]      = disp["CM2_VAR"].apply(
        lambda x: fmt_lakhs(x, signed=True))

    _rev_n2   = pd.to_numeric(df["REV_PCT"],          errors="coerce").reset_index(drop=True)
    _cm2a_n2  = pd.to_numeric(df["CM2_ABS_ACHVD_PCT"], errors="coerce").reset_index(drop=True)
    _var_n2   = pd.to_numeric(df["CM2_VAR"],           errors="coerce").reset_index(drop=True)
    _lag_r_n2 = disp["_LAG_REV"].reset_index(drop=True)
    _lag_u_n2 = disp["_LAG_UNITS"].reset_index(drop=True)
    _acos_delta_sc = (pd.to_numeric(df["ACOS_PCT_ACT"], errors="coerce") -
                      pd.to_numeric(df["ACOS_PCT_BUD"], errors="coerce")).reset_index(drop=True)
    _cm2pct_delta_sc = (pd.to_numeric(df["CM2_PCT_ACT"], errors="coerce") -
                        pd.to_numeric(df["CM2_PCT_BUD"], errors="coerce")).reset_index(drop=True)

    dcols2 = ["SUB_CATEGORY","Budget Rev","Actual Rev","Lag(R)","Lag(U)","% Achieved",
              "Budget CM1","Actual CM1","Act ACoS%","Bud ACoS%",
              "Budget CM2","Actual CM2","Act CM2%","Bud CM2%",
              "CM2 Abs %","CM2 Var"]
    table_df2 = disp[dcols2].rename(columns={"SUB_CATEGORY":"Sub-Category"}).reset_index(drop=True)

    def _lag_style(v):
        if v is None or pd.isna(v) or v == 0:
            return ""
        return ("color:#8b1a1a;font-weight:600" if v > 0
                else "color:#004A2B;font-weight:600")

    def style_v2(row):
        s = [""] * len(row)
        idx = row.index.tolist()
        s[idx.index("% Achieved")]  = color_pct(_rev_n2.iloc[row.name])
        s[idx.index("CM2 Abs %")]   = color_pct(_cm2a_n2.iloc[row.name])
        s[idx.index("CM2 Var")]     = color_var(_var_n2.iloc[row.name])
        # Lag(R) / Lag(U): positive (behind plan) red, negative (ahead) green
        s[idx.index("Lag(R)")] = _lag_style(_f(_lag_r_n2.iloc[row.name]))
        s[idx.index("Lag(U)")] = _lag_style(_f(_lag_u_n2.iloc[row.name]))
        # Act ACoS% vs Bud: lower is better
        av = _f(_acos_delta_sc.iloc[row.name])
        if av is not None:
            s[idx.index("Act ACoS%")] = (
                "color:#8b1a1a;font-weight:600" if av > 0
                else "color:#004A2B;font-weight:600")
        # Act CM2% vs Bud: higher is better
        cv = _f(_cm2pct_delta_sc.iloc[row.name])
        if cv is not None:
            s[idx.index("Act CM2%")] = (
                "color:#004A2B;font-weight:600" if cv > 0
                else "color:#8b1a1a;font-weight:600")
        if row["Sub-Category"] == "GRAND TOTAL":
            s = [(x + TOTAL_ROW).lstrip(";") for x in s]
        return s

    event = st.dataframe(
        table_df2.style.apply(style_v2, axis=1).hide(axis="index"),
        use_container_width=True, height=550,
        column_config={
            "Lag(R)": st.column_config.NumberColumn(
                "Lag(R)",
                help="Budget Revenue − Actual Revenue. "
                     "Positive = behind plan, negative = ahead of plan. "
                     "Sortable by clicking the column header.",
                format=f"{sym}%+,.0f",
            ),
            "Lag(U)": st.column_config.NumberColumn(
                "Lag(U)",
                help="Budget Units − Actual Units. "
                     "Positive = behind plan, negative = ahead of plan.",
                format="%+,.0f",
            ),
        },
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
        # Default sort: best revenue first. Users can re-sort by clicking any
        # column header in the table below (st.dataframe gives native
        # multi-direction sort on every column).
        if "ACT_REVENUE" in df.columns:
            df = df.sort_values("ACT_REVENUE", ascending=False,
                                na_position="last").reset_index(drop=True)

        cc1, cc2 = st.columns([2, 8])
        with cc1:
            top_n = st.selectbox("Show",
                                 ["All", "Top 10", "Top 20", "Top 50"],
                                 index=0, key=f"asin_topn_{geo}_{subcat}")
        with cc2:
            st.markdown(
                f'<div style="padding-top:32px;font-size:11.5px;color:#7a6a50;">'
                f'<b>{len(df):,}</b> ASINs in {subcat} · {geo} &nbsp;·&nbsp; '
                f'click any column header to re-sort.</div>',
                unsafe_allow_html=True)
        if top_n != "All":
            n = int(top_n.split()[1])
            df = df.head(n).reset_index(drop=True)

        st.caption(
            "All budget figures from P&L table for the same date range. "
            "Actuals = total sales (organic + paid). "
            "**Lag** = Bud Rev − Act Rev (positive = behind plan). "
            "**Cover Days** = Total Inv ÷ max daily run-rate across "
            "(7d, 14d, 30d). 🔴 < 20 days (or out of stock) · 🟡 20–40 days."
        )
        # Conditional inventory columns: USA shows FBA + ADW + Total,
        # other GEOs collapse to just Total (since Total = FBA).
        is_usa_view = (geo or "").upper() == "USA"
        if is_usa_view:
            inv_cols = [
                ("FBA_INV",    "FBA Inv"),
                ("ADW_INV",    "ADW Inv"),
                ("TOTAL_INV",  "Total Inv"),
                ("COVER_DAYS", "Cover Days"),
            ]
        else:
            inv_cols = [
                ("TOTAL_INV",  "Total Inv"),
                ("COVER_DAYS", "Cover Days"),
            ]

        # Lag(R) = Bud Rev - Act Rev (positive = behind plan)
        # Lag(U) = Bud Units - Act Units
        df["_LAG_REV"]   = (pd.to_numeric(df["BUD_REVENUE"], errors="coerce") -
                            pd.to_numeric(df["ACT_REVENUE"], errors="coerce"))
        df["_LAG_UNITS"] = (pd.to_numeric(df["BUD_UNITS"],   errors="coerce") -
                            pd.to_numeric(df["ACT_UNITS"],   errors="coerce"))

        pnl_cols = [
            ("ASIN",          "ASIN"),
            ("PRODUCT_NAME",  "Product"),
            ("BRAND",         "Brand"),
            ("ACT_UNITS",     "Act Units"),
            ("BUD_UNITS",     "Bud Units"),
            ("_LAG_UNITS",    "Lag(U)"),
            ("ACT_REVENUE",   "Act Rev"),
            ("BUD_REVENUE",   "Bud Rev"),
            ("_LAG_REV",      "Lag(R)"),
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
        ] + inv_cols
        p = df[[c for c,_ in pnl_cols]].rename(columns=dict(pnl_cols)).copy()
        p["Act Units"] = p["Act Units"].apply(fmt_num)
        p["Bud Units"] = p["Bud Units"].apply(fmt_num)
        p["Act Rev"]   = df["ACT_REVENUE"].apply(fmt_lakhs)
        p["Bud Rev"]   = df["BUD_REVENUE"].apply(fmt_lakhs)
        # Lag(R) / Lag(U) stay NUMERIC for correct sort. Display formatting
        # comes from st.column_config.NumberColumn at the st.dataframe call.
        p["Lag(R)"]    = pd.to_numeric(df["_LAG_REV"],   errors="coerce")
        p["Lag(U)"]    = pd.to_numeric(df["_LAG_UNITS"], errors="coerce")
        p["CM2 Abs"]   = df["ACT_CM2_ABS"].apply(fmt_lakhs)
        p["Act ASP"]   = df["ACT_ASP"].apply(lambda v: fmt_ccy(v))
        p["Bud ASP"]   = df["BUD_ASP"].apply(lambda v: fmt_ccy(v))
        for col in ["Rev %","Act CM1%","Bud CM1%","Act ACoS%","Bud ACoS%","Act CM2%","Bud CM2%"]:
            src = [c for c,n in pnl_cols if n == col][0]
            p[col] = df[src].apply(fmt_pct)
        # Inventory + cover-days formatting
        if is_usa_view:
            p["FBA Inv"] = df["FBA_INV"].apply(
                lambda v: "—" if (_f(v) is None or _f(v) == 0) else f"{int(_f(v)):,}")
            p["ADW Inv"] = df["ADW_INV"].apply(
                lambda v: "—" if (_f(v) is None or _f(v) == 0) else f"{int(_f(v)):,}")
        p["Total Inv"] = df["TOTAL_INV"].apply(
            lambda v: "—" if (_f(v) is None or _f(v) == 0) else f"{int(_f(v)):,}")
        p["Cover Days"] = df["COVER_DAYS"].apply(
            lambda v: "—" if _f(v) is None else f"{_f(v):,.1f}")

        _rev_achvd   = pd.to_numeric(df["REV_ACHVD_PCT"], errors="coerce").reset_index(drop=True)
        _acos_delta  = (pd.to_numeric(df["ACT_ACOS_PCT"], errors="coerce") -
                        pd.to_numeric(df["BUD_ACOS_PCT"], errors="coerce")).reset_index(drop=True)
        _cm2_delta   = (pd.to_numeric(df["ACT_CM2_PCT"], errors="coerce") -
                        pd.to_numeric(df["BUD_CM2_PCT"], errors="coerce")).reset_index(drop=True)
        _cover_days  = pd.to_numeric(df["COVER_DAYS"], errors="coerce").reset_index(drop=True)
        _total_inv_n = pd.to_numeric(df["TOTAL_INV"],   errors="coerce").reset_index(drop=True)
        _lag_r_n     = pd.to_numeric(df["_LAG_REV"],   errors="coerce").reset_index(drop=True)
        _lag_u_n     = pd.to_numeric(df["_LAG_UNITS"], errors="coerce").reset_index(drop=True)

        p = p.reset_index(drop=True)

        def _lag_style(v):
            if v is None or pd.isna(v) or v == 0:
                return ""
            return ("color:#8b1a1a;font-weight:600" if v > 0
                    else "color:#004A2B;font-weight:600")

        def style_pnl(row):
            s = [""] * len(row)
            idx = row.index.tolist()
            if "Rev %" in idx:
                s[idx.index("Rev %")]     = color_pct(_rev_achvd.iloc[row.name])
            if "Lag(R)" in idx:
                s[idx.index("Lag(R)")] = _lag_style(_f(_lag_r_n.iloc[row.name]))
            if "Lag(U)" in idx:
                s[idx.index("Lag(U)")] = _lag_style(_f(_lag_u_n.iloc[row.name]))
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
            # Highlight low Cover Days (<20) red; medium (20-40) amber.
            # Out-of-stock rows (Total Inv = 0) ALSO get the red treatment.
            if "Cover Days" in idx:
                cd = _f(_cover_days.iloc[row.name])
                ti = _f(_total_inv_n.iloc[row.name])
                if (ti is not None and ti == 0) or (cd is not None and cd < 20):
                    style = ("background-color:#fde8e8;color:#8b1a1a;"
                             "font-weight:700")
                    s[idx.index("Cover Days")] = style
                    if "Total Inv" in idx:
                        s[idx.index("Total Inv")] = style
                elif cd is not None and cd < 40:
                    s[idx.index("Cover Days")] = (
                        "background-color:#fef3d6;color:#7a5c00;font-weight:600")
            return s

        st.caption("💡 **Click any row** to open the ASIN's daily deep-dive "
                   "(revenue, units, spend, ACoS, ASP over time).")
        evt_pnl = st.dataframe(
            p.style.apply(style_pnl, axis=1).hide(axis="index"),
            use_container_width=True, height=500,
            column_config={
                # Numeric formatting + correct numeric sort on click.
                "Lag(R)": st.column_config.NumberColumn(
                    "Lag(R)",
                    help="Budget Revenue − Actual Revenue. "
                         "Positive = behind plan, negative = ahead of plan. "
                         "Click the header to sort numerically.",
                    format=f"{sym}%+,.0f",
                ),
                "Lag(U)": st.column_config.NumberColumn(
                    "Lag(U)",
                    help="Budget Units − Actual Units. "
                         "Positive = behind plan, negative = ahead of plan.",
                    format="%+,.0f",
                ),
            },
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

    # 7/30/90-day comparable buckets (Amazon-style). These use an
    # INDEPENDENT 90-day query so they are always correct even when the user
    # selects a short window like "Last 7 Days" in the period selector.
    with st.spinner("Loading 90-day rolling stats…"):
        roll = get_asin_rolling(asin, geo, sfx)

    def _window90(days):
        if roll.empty:
            return roll
        cutoff = today_ - timedelta(days=days - 1)
        return roll[roll["DAY"] >= pd.Timestamp(cutoff)]
    last7   = _window90(7);   last30 = _window90(30);   last90 = _window90(90)

    def _sumlbl(slice_, col):
        if slice_.empty or col not in slice_.columns:
            return None
        v = _f(slice_[col].sum())
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

    def _row(label, slice_):
        u   = _sumlbl(slice_, "UNITS")
        r   = _sumlbl(slice_, "REVENUE")
        sp  = _sumlbl(slice_, "SPEND")
        ses = _sumlbl(slice_, "SESSIONS")
        asp = (r / u) if (r is not None and u) else None
        cr  = (u / ses * 100.0) if (u is not None and ses) else None
        return {"Window": label,
                "Units ordered": u,
                "Sessions":      ses,
                "CR%":           cr,
                "Revenue":       r,
                "Avg ASP":       asp,
                "Spend":         sp}

    rolling = pd.DataFrame([
        _row("Last 7 days",  last7),
        _row("Last 30 days", last30),
        _row("Last 90 days", last90),
    ])
    rolling["Units ordered"] = rolling["Units ordered"].apply(
        lambda v: "—" if v is None else f"{v:,.0f}")
    rolling["Sessions"] = rolling["Sessions"].apply(
        lambda v: "—" if v is None or v == 0 else f"{v:,.0f}")
    rolling["CR%"] = rolling["CR%"].apply(
        lambda v: "—" if v is None else f"{v:.1f}%")
    rolling["Revenue"] = rolling["Revenue"].apply(fmt_lakhs)
    rolling["Avg ASP"] = rolling["Avg ASP"].apply(
        lambda v: "—" if v is None else f"{sym}{v:,.2f}")
    rolling["Spend"]   = rolling["Spend"].apply(fmt_lakhs)
    st.dataframe(rolling, use_container_width=True, hide_index=True)
    st.caption(
        "Rolling windows are computed from the last 90 days "
        "regardless of the period selector above. "
        "CR% = Units ÷ Sessions (sessions from "
        "`vahdam_amazon_sales_marketing`; “—” means the table or column "
        "isn't available for this GEO)."
    )

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
# Marketplace domain per GEO (shown in the tab caption)
AMAZON_DOMAIN = {
    "USA": "amazon.com", "UK": "amazon.co.uk", "DE": "amazon.de",
    "FR": "amazon.fr",   "IT": "amazon.it",    "ES": "amazon.es",
    "CA": "amazon.ca",
}

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

_USA_ASINS = [
    "B0B293XFM4","B096KXJFVP","B09Y9G1436","B0BT7H247Z","B07RGK5QKZ",
    "B07MNSWD6D","B00R65SD4C","B0BB1LXSPN","B096KZ74F1","B0DPWQWZYX",
    "B096KWR1PK","B09Y9DYSD6","B09Y9BGBTF","B017P6DS5A","B09YY7BCZ3",
    "B00VFYPK82","B0C7N1F4Y1","B0BYHYKHG8","B09YY78NFQ","B00VBUY3SS",
    "B097HLWC93","B09Y9DJ6DW","B096KTV5QP","B0BCKFGKFQ","B07MDCXFWQ",
    "B00VFYPIDO","B01JAK7UAS","B0C9CJ8L3N","B00VFYPG1S","B09R784RYL",
    "B0186XTAUI","B019FLGKZI","B08G8SDB6D","B09YXMVQTV","B0BT7FB4MC",
    "B0F5VQN2NR","B0BYK1F7Q8","B01M0DB0Z3","B0757VW95S","B00Q6FM6GY",
    "B074L4MZRY","B07RHN9TDF","B0F5W48J88","B0C7439B81","B0CJF7L293",
    "B0BFHKDK88","B01K78VZE4","B09PV23QJQ","B0C7454VNB","B00S0NYCCG",
    "B016IL75S4","B00VIDZ378","B09YXT3C1L","B097HLJLM2","B0B2928XNH",
    "B016IJ0YY8","B09K45FNBH","B097HRWHZQ","B09PV2CV6Z","B00ZUTOATI",
    "B07RJRJC7V","B0DPXK81SW","B09Y9CJZZH","B08G2J7HJ7","B00XL1E6QO",
    "B01MG3L67M","B0C33Q1FSB","B07SRFW87H","B09PLDGY6J","B0C7N124LZ",
    "B00MN668VY","B07M61PL9K","B0B5LPWSGH","B07RGK4H2B","B09Y9BJVJR",
    "B096KWCHG2","B00VLOCBHE","B07QQQRPCL","B07R6MHNMB","B0BCKGS74K",
    "B0BN7XPNNL","B096KWDSVD","B07SVNLZ97","B07RDK9WTN","B08G2J583H",
    "B096KXXFY6","B013P6ZFHI","B09PV289KH","B096V4F6L5","B01J3F13O4",
    "B093663R1Q","B07MNSZ61S","B09Y9DWNPZ","B09Y9D4WJQ","B07RFLKDTN",
    "B09PV64FGX","B09K461LQL","B097HMDY2H","B013P9H1AY","B07K1WBH4K",
    "B075XQXSLM","B019TVPHYO","B0BZCPMQ36","B09R1PSLYW","B07RHN6RRX",
    "B08G1XMCKC","B00Q6UN3ZM","B07583WVRF","B0757M47FW","B01M7RQOE5",
    "B07RLM88NM","B00VK0LF0S","B0757QHYVK","B016KQXYZA","B09KCFX4H3",
    "B08G2J4MVZ","B01J3G9C5U","B00VIDY1GC","B00M59AHAC","B0B31QY94Q",
    "B00M59HKMK","B01M01OIYT","B07RHN9RVP","B01NA9WRZF","B0757NZHK7",
    "B01LZPUA82","B07K1XSGBK","B01DZOZJNA","B01M4MJ7FP","B08LVZV78R",
    "B0C7N1DHBX","B01LZZZVKD","B08G2LFLCG","B08G2L3P89","B088LV4F48",
    "B00N8JNFD4","B07RGK61WK","B01KCG2OP0","B07RKWCXMB","B08G1ZFC42",
    "B0757N4D53","B0D54CSMKV","B0D54DF9WQ","B075XQDG97","B01B5Z1624",
    "B00VIDYKKE","B09YXRHRGX","B08G1X8T6S","B09PV32JKR","B09PTZCM55",
    "B09RZKP6DK","B00WSQU9DW","B00M56WWX0","B01KCH8O3K","B07RBN3ZMJ",
    "B07MD4LB49","B075XR382W","B01M8LP7O3","B0DK5JHV4Q","B014WCN60M",
    "B00VIDZ72Y","B08LVZ44TS","B0757QPXFR","B09PV47Z2Q","B096QC2CC7",
    "B01M706JM3","B09K45YFYL","B00VIDXHTO","B075XRJB6S","B00VIDX8V6",
    "B015J2V2NC","B015J3FXOU","B09K453RMM","B00Q8LVPOU","B00R4O1H0M",
    "B06X6BB1JM","B08LVX5P5G","B06W5B8F5G","B00Q492AS6","B09PV4NDN3",
    "B00VNWWV10","B00MN8CJME","B0D6BNFJFJ","B078J3C15N","B0DK5HKNTJ",
    "B076HSFRQF","B0DK5JW2NK","B0DK5HF8RY","B0DK5GQ9FP","B0FSDLB9N4",
    "B00PZRTIKQ","B0C23KF9RY","B0D9M7KFD2","B09HS7BMB5","B098XH87N9",
    "B0B53RF2VB","B0FLDRSHZY","B0FLQGFHJ2","B0D9M8MZ5S","B09K44N7MK",
    "B0C7MZSNHL","B0FLQK45YC","B09PV561PB","B0FLDXPTW1","B0FLQLMV1H",
    "B0FLQHD86G","B0FLQJLCQP","B07ZB61GXF","B09SZGSWSZ","B0C7GZDBGV",
    "B095PV3YYG","B0D676STMS","B0FFBDXQ5Y","B08Y5QJHB5","B0C8ST8KVL",
    "B0C741NRPK","B0C8ZDBRGG","B08FXWK7LT","B09K45HC68","B01JAA4XB2",
    "B0FLQJ354G","B0C1VCYM63","B0FCML85FV","B0FFBM89G7","B0FFBHMQV8",
    "B0FLDWDHG8","B09SZF4X4Z","B0D675PBMK","B0FLDWW2HL","B0BZZHPXQN",
    "B0D6GMGTF1","B0FFBGHWQF","B09SZDDSG9","B0BJKYBC83","B0BJ75PLV7",
    "B0D5MQ8XQM","B0BJL42LJH","B09SZGG4S7",
]

PRICE_TRACKER_ASINS = {
    "USA": _USA_ASINS,
    "UK":  _UK_ASINS,
    "DE":  _EU_ASINS,
    "FR":  _EU_ASINS,
    "IT":  _EU_ASINS,
    "ES":  _EU_ASINS,
    "CA":  _CA_ASINS,
}

# Budgeted (target) selling price per GEO per ASIN, in the marketplace's
# native currency. When set, the anomaly check compares the latest price to
# the budget instead of the trailing 7-day average. Fill in as needed:
#   PRICE_BUDGETS["USA"]["B0XXXXXXXX"] = 24.99
PRICE_BUDGETS: dict = {
    "USA": {},
    "UK":  {},
    "DE":  {},
    "FR":  {},
    "IT":  {},
    "ES":  {},
    "CA":  {},
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


def _value_as_of(csv_arr, target_dt):
    """Return the raw value in a Keepa csv array as of `target_dt` (the latest
    point on or before that datetime). Returns None if no such point exists.
    `csv_arr` is the raw alternating [keepa_minute, value, ...] array — value
    may be -1 (no buybox / out of stock)."""
    if not csv_arr or len(csv_arr) < 2:
        return None
    import datetime as _d
    KEEPA_EPOCH = _d.datetime(2011, 1, 1)
    target_min = int((target_dt - KEEPA_EPOCH).total_seconds() // 60)
    last_val = None
    for i in range(0, len(csv_arr) - 1, 2):
        km = csv_arr[i]
        if km <= target_min:
            last_val = csv_arr[i + 1]
        else:
            break
    return last_val


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

        # Buybox status: based on YESTERDAY's data point (i.e. the most recent
        # csv[18] value at least 24h old). This filters out transient blips
        # where the buybox briefly drops out / is reassigned today.
        # -1 = no buybox at that moment (suppressed / no offer winning).
        import datetime as _d
        yesterday_dt = _d.datetime.utcnow() - _d.timedelta(days=1)
        y_raw_18 = _value_as_of(buybox_arr, yesterday_dt)
        y_raw_32 = _value_as_of(buybox2_arr, yesterday_dt)
        if y_raw_18 is not None:
            buybox_present = y_raw_18 >= 0
            buybox_yesterday = (float(y_raw_18) / 100.0) if y_raw_18 >= 0 else None
        elif y_raw_32 is not None:
            buybox_present = y_raw_32 >= 0
            buybox_yesterday = (float(y_raw_32) / 100.0) if y_raw_32 >= 0 else None
        else:
            buybox_present = None  # unknown — no history yet
            buybox_yesterday = None

        out[asin] = {
            "title":            prod.get("title", asin),
            "currency":         sym,
            "amazon_pts":       amazon_pts,
            "new_pts":          new_pts,
            "buybox_pts":       buybox_pts,
            "last_amazon":      _last(amazon_pts),
            "last_new":         _last(new_pts),
            "last_buybox":      _last(buybox_pts),
            "buybox_present":   buybox_present,
            "buybox_yesterday": buybox_yesterday,
            "stats":            prod.get("stats", {}),
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


def _detect_price_anomaly(pts, lookback_days=7, threshold_pct=15.0,
                          budget=None):
    """Flag if the most recent price deviates > threshold_pct from the
    baseline. Baseline is the budgeted price when provided, otherwise the
    average of the prior `lookback_days` (the 7 days immediately before the
    latest point).

    Returns dict with 'flag': bool, 'change_pct': float, 'last': float,
    'baseline': float, 'direction': 'up'|'down'|None, 'basis': 'budget'|'7d'.
    """
    if not pts:
        return {"flag": False}
    import datetime as _d
    last_dt, last_price = pts[-1]
    if budget and budget > 0:
        baseline = float(budget)
        basis = "budget"
    else:
        if len(pts) < 2:
            return {"flag": False}
        window_start = last_dt - _d.timedelta(days=lookback_days)
        prior = [p for d, p in pts[:-1] if d >= window_start]
        if not prior:
            return {"flag": False}
        baseline = sum(prior) / len(prior)
        basis = "7d"
    if baseline == 0:
        return {"flag": False}
    change = (last_price - baseline) / baseline * 100
    return {
        "flag":       abs(change) >= threshold_pct,
        "change_pct": change,
        "last":       last_price,
        "baseline":   baseline,
        "direction":  "up" if change > 0 else "down",
        "basis":      basis,
    }


def render_price_tracker():
    """Price Tracker view: per-GEO tabs, Keepa price charts, anomaly highlights."""
    st.markdown('<div class="page-title">Price Tracker</div>',
                unsafe_allow_html=True)
    st.markdown(
        '<div class="page-sub">Keepa-tracked price history per ASIN '
        '&nbsp;&bull;&nbsp; flagged when last price deviates >15% from the '
        'budgeted price (or prior 7-day average when no budget is set) '
        '&nbsp;&bull;&nbsp; data refreshes every 24 h '
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
            domain_str = AMAZON_DOMAIN.get(geo, "amazon.com")
            budgets = PRICE_BUDGETS.get(geo, {}) or {}
            st.caption(f"{len(asins)} ASIN{'s' if len(asins) != 1 else ''} "
                       f"on {domain_str} · Keepa domain {domain}")

            with st.spinner(f"Fetching Keepa data for {len(asins)} ASINs…"):
                data = fetch_keepa_products(tuple(asins), domain)

            if "_error" in data:
                st.error(data["_error"])
                continue

            # ── Buybox-missing summary (based on YESTERDAY) ──
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
                                f"without an active Buy Box (yesterday)")
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
                            "Buy Box suppressed / unavailable as of yesterday:</div>",
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

            # ── Anomaly summary (uses budget when present, else 7-day avg) ──
            anomalies = []
            for asin in asins:
                if asin not in data: continue
                d = data[asin]
                pts = d["amazon_pts"] or d["new_pts"]
                a = _detect_price_anomaly(pts, budget=budgets.get(asin))
                if a.get("flag"):
                    anomalies.append((asin, d, a))

            if anomalies:
                st.markdown(
                    f'<div class="alerts-row">'
                    f'<div class="alert-banner alert-warn">⚠️ {len(anomalies)} '
                    f'price {"anomaly" if len(anomalies) == 1 else "anomalies"} '
                    f'— review below.</div></div>',
                    unsafe_allow_html=True)
                with st.expander(f"⚠️ {len(anomalies)} anomalies — show details",
                                 expanded=True):
                    for asin, d, a in anomalies:
                        arrow = "▲" if a["direction"] == "up" else "▼"
                        color = "#1a7a3e" if a["direction"] == "up" else "#8b1a1a"
                        title = d['title'][:70]
                        basis_lbl = ("vs budget" if a.get("basis") == "budget"
                                     else "vs 7-day avg")
                        st.markdown(
                            f"<div style='padding:6px 0;border-bottom:1px dashed #ede4d0;'>"
                            f"<b>{asin}</b> &nbsp;·&nbsp; "
                            f"<span style='color:{color};font-weight:700;'>"
                            f"{arrow} {abs(a['change_pct']):.1f}%</span> "
                            f"<span class='small-muted' style='font-size:10.5px;'>"
                            f"{basis_lbl}</span> "
                            f"&nbsp;<span class='small-muted'>"
                            f"{d['currency']}{a['baseline']:.2f} → "
                            f"{d['currency']}{a['last']:.2f}</span><br>"
                            f"<span style='font-size:11.5px;color:#7a6a50;'>"
                            f"{title}</span></div>",
                            unsafe_allow_html=True)
            else:
                st.success("✓ No price anomalies detected.")

            # ── ASIN search / picker ──
            st.markdown('<div class="section-hdr" style="margin-top:18px;">'
                        'Price history (Amazon + New offer)</div>',
                        unsafe_allow_html=True)

            # Build a label map: "ASIN — Title" for each ASIN that came back.
            # Anomalies / buybox-missing bubble to the top of the dropdown.
            def _label_for(a):
                t = (data.get(a, {}).get("title") or "")[:60]
                return f"{a} — {t}" if t else a
            anomaly_set = {a[0] for a in anomalies}
            missing_set = {a[0] for a in missing_buybox}
            def _sort_key(a):
                # 0 = anomaly, 1 = missing buybox, 2 = rest
                if a in anomaly_set: return (0, a)
                if a in missing_set: return (1, a)
                return (2, a)
            options = sorted(asins, key=_sort_key)
            search_q = st.text_input(
                "🔍 Search ASIN or title",
                key=f"price_search_{geo}",
                placeholder="e.g. B0BJK5GPRD or 'masala chai'",
            ).strip().lower()
            if search_q:
                options = [
                    a for a in options
                    if search_q in a.lower()
                    or search_q in (data.get(a, {}).get("title") or "").lower()
                ]
                if not options:
                    st.info(f"No ASINs matched “{search_q}”.")
                    continue
            # Default: any anomaly / missing-buybox ASINs (capped at 6), else
            # the first 3 ASINs so the page loads quickly.
            default_picks = [a for a in options
                             if a in anomaly_set or a in missing_set][:6]
            if not default_picks:
                default_picks = options[:3]
            picks = st.multiselect(
                f"Select ASINs to chart ({len(options)} available)",
                options=options,
                default=default_picks,
                format_func=_label_for,
                key=f"price_picks_{geo}",
            )
            if not picks:
                st.info("Pick one or more ASINs above to see their price charts.")
                continue

            # ── Per-ASIN price charts (3 per row) ──
            import datetime as _d
            two_years_ago = _d.datetime.utcnow() - _d.timedelta(days=730)

            ROW = 3
            for row_start in range(0, len(picks), ROW):
                cols = st.columns(ROW, gap="medium")
                for i, asin in enumerate(picks[row_start:row_start + ROW]):
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
                        budget_price = budgets.get(asin)

                        # Restrict pts to last 2 years for both anomaly + chart
                        amazon_pts_2y = [p for p in d["amazon_pts"]
                                         if p[0] >= two_years_ago]
                        new_pts_2y    = [p for p in d["new_pts"]
                                         if p[0] >= two_years_ago]

                        # Price header
                        last = d.get("last_amazon") or d.get("last_new") or d.get("last_buybox")
                        last_label = ("Amazon" if d.get("last_amazon")
                                      else "New" if d.get("last_new")
                                      else "Buy Box" if d.get("last_buybox")
                                      else "—")
                        last_str = f"{d['currency']}{last:.2f}" if last else "—"
                        anomaly = _detect_price_anomaly(
                            amazon_pts_2y or new_pts_2y,
                            budget=budget_price)
                        bb_missing = d.get("buybox_present") is False
                        bb_yday    = d.get("buybox_yesterday")
                        if bb_missing:
                            bord = "#8b1a1a"
                        elif anomaly.get("flag"):
                            bord = "#AB8743"
                        else:
                            bord = "#d6ccba"
                        flag_html = ""
                        if bb_missing:
                            flag_html = ("<span style='color:#8b1a1a;font-weight:700;"
                                         "font-size:11px;'>🛒 No Buy Box (yest.)</span>")
                        elif anomaly.get("flag"):
                            arrow = "▲" if anomaly["direction"] == "up" else "▼"
                            clr = "#1a7a3e" if anomaly["direction"] == "up" else "#8b1a1a"
                            basis_tag = ("vs budget" if anomaly.get("basis") == "budget"
                                         else "vs 7d avg")
                            flag_html = (f"<span style='color:{clr};font-weight:700;"
                                          f"font-size:11px;'>{arrow} "
                                          f"{abs(anomaly['change_pct']):.1f}% "
                                          f"<span style='font-weight:500;color:#7a6a50;'>"
                                          f"{basis_tag}</span></span>")
                        budget_html = ""
                        if budget_price:
                            budget_html = (f"<span class='small-muted' "
                                           f"style='font-size:10.5px;'>Budget "
                                           f"{d['currency']}{budget_price:.2f}</span>")
                        bb_yday_html = ""
                        if bb_yday is not None and not bb_missing:
                            bb_yday_html = (f"<span class='small-muted' "
                                            f"style='font-size:10.5px;'>BB yest. "
                                            f"{d['currency']}{bb_yday:.2f}</span>")
                        meta_html = " &nbsp;·&nbsp; ".join(
                            x for x in [budget_html, bb_yday_html] if x)
                        if meta_html:
                            meta_html = (f"<div style='font-size:10.5px;"
                                         f"color:#7a6a50;margin-top:2px;'>"
                                         f"{meta_html}</div>")
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
                            f"{meta_html}"
                            f"</div>", unsafe_allow_html=True)

                        # Mini Plotly chart — last 2 years only
                        if HAS_PLOTLY and (amazon_pts_2y or new_pts_2y):
                            fig = go.Figure()
                            if amazon_pts_2y:
                                xs, ys = zip(*amazon_pts_2y)
                                fig.add_trace(go.Scatter(
                                    x=xs, y=ys, mode="lines",
                                    name="Amazon",
                                    line=dict(color="#004A2B", width=1.6),
                                    hovertemplate=(f"<b>%{{x|%d %b %Y}}</b><br>"
                                                   f"Amazon: {d['currency']}%{{y:.2f}}"
                                                   "<extra></extra>")))
                            if new_pts_2y:
                                xs, ys = zip(*new_pts_2y)
                                fig.add_trace(go.Scatter(
                                    x=xs, y=ys, mode="lines",
                                    name="New",
                                    line=dict(color="#AB8743", width=1.2,
                                              dash="dot"),
                                    hovertemplate=(f"<b>%{{x|%d %b %Y}}</b><br>"
                                                   f"New: {d['currency']}%{{y:.2f}}"
                                                   "<extra></extra>")))
                            # Budget horizontal reference line
                            if budget_price:
                                fig.add_hline(
                                    y=budget_price,
                                    line=dict(color="#8b1a1a", width=1.1,
                                              dash="dash"),
                                    annotation_text=(f"Budget "
                                                     f"{d['currency']}"
                                                     f"{budget_price:.2f}"),
                                    annotation_position="top left",
                                    annotation_font=dict(size=9,
                                                         color="#8b1a1a"),
                                )
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
                            fig.update_xaxes(
                                showgrid=False,
                                tickfont=dict(size=9, color="#7a6a50"),
                                nticks=4,
                                range=[two_years_ago, _d.datetime.utcnow()],
                            )
                            fig.update_yaxes(showgrid=True,
                                              gridcolor="rgba(171,135,67,0.15)",
                                              tickfont=dict(size=9, color="#7a6a50"),
                                              tickprefix=d["currency"],
                                              nticks=4)
                            st.plotly_chart(fig, use_container_width=True,
                                            config={"displayModeBar": False})
                        else:
                            st.caption("No history available (last 2 years)")


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

# ═══════════════════════════════════════════════════════════════════════════════
# VIEW 6 — Customer Insights
# ═══════════════════════════════════════════════════════════════════════════════
# Theme columns in the reviews table. (column_in_table, display_label)
_REVIEW_THEMES = [
    ("T_DISLIKE",     "General Taste Dislike"),
    ("T_LIGHT_TASTE", "Light taste"),
    ("T_STRONG_TASTE","Strong Taste"),
    ("T_HEALTH",      "Health Issue"),
    ("T_PRICE",       "Price"),
    ("T_PACK",        "Other Packaging"),
    ("T_TEABAG",      "Tea Bag Related"),
    ("T_MISSING",     "Missing items"),
    ("T_ODOUR",       "Odour"),
    ("T_TEXTURE",     "Texture"),
    ("T_DELIVERY",    "Delivery"),
    ("T_LISTING",     "Listing"),
    ("T_OTHERS",      "Others"),
    ("T_ANIMAL",      "Animal"),
]


@st.cache_data(ttl=900, show_spinner=False)
def get_reviews_all():
    """Pull every review row with normalized columns + parsed date.

    The source table mixes two date formats ("November 10, 2025" for USA/India,
    "1 April 2026" for EU/UK) and has a header-pollution row with all blanks,
    so we filter both out here. Theme columns are kept as raw text — a review
    "mentions" a theme when the column is non-empty.
    Cached 15 min."""
    df = run_query(f"""
        SELECT
            UPPER(TRIM(GEO))                            AS GEO,
            UPPER(TRIM(ASIN))                           AS ASIN,
            NAME                                        AS PRODUCT_NAME,
            UPPER(TRIM(BRAND))                          AS BRAND,
            UPPER(TRIM(CATEGORY))                       AS CATEGORY,
            "Sub Category"                              AS SUB_CATEGORY,
            TRY_TO_NUMBER(RATING)                       AS RATING,
            COALESCE(
                TRY_TO_DATE(DATE, 'MMMM DD, YYYY'),
                TRY_TO_DATE(DATE, 'DD MMMM YYYY'),
                TRY_TO_DATE(DATE, 'DD/MM/YYYY'),
                TRY_TO_DATE(DATE, 'MM/DD/YYYY'),
                TRY_TO_DATE(DATE, 'YYYY-MM-DD')
            )                                           AS REVIEW_DATE,
            "Review Description"                        AS REVIEW_TEXT,
            "Review title"                              AS REVIEW_TITLE,
            "Light taste"                               AS T_LIGHT_TASTE,
            "Health Issue"                              AS T_HEALTH,
            "Strong Taste"                              AS T_STRONG_TASTE,
            "General Taste Dislike"                     AS T_DISLIKE,
            "Other Packaging"                           AS T_PACK,
            "Tea Bag Related"                           AS T_TEABAG,
            "Missing items"                             AS T_MISSING,
            PRICE                                       AS T_PRICE,
            ODOUR                                       AS T_ODOUR,
            TEXTURE                                     AS T_TEXTURE,
            OTHERS                                      AS T_OTHERS,
            LISTING                                     AS T_LISTING,
            DELIVERY                                    AS T_DELIVERY,
            ANIMAL                                      AS T_ANIMAL
        FROM {REVIEWS}
        WHERE ASIN IS NOT NULL AND TRIM(ASIN) <> ''
          AND GEO IS NOT NULL AND TRIM(GEO) <> ''
          AND UPPER(TRIM(GEO)) <> 'GEO'
          AND TRY_TO_NUMBER(RATING) IS NOT NULL
    """)
    if df.empty:
        return df
    df["REVIEW_DATE"] = pd.to_datetime(df["REVIEW_DATE"], errors="coerce")
    df["RATING"]      = pd.to_numeric(df["RATING"], errors="coerce")
    # Sentiment buckets
    df["NEGATIVE"] = df["RATING"] <= 2
    df["NEUTRAL"]  = df["RATING"] == 3
    df["POSITIVE"] = df["RATING"] >= 4
    # Convenience: month bucket
    df["YEAR_MONTH"] = df["REVIEW_DATE"].dt.to_period("M").astype(str)
    return df


def _theme_counts(slice_df):
    """Return DataFrame[theme, n] sorted desc — counts non-empty theme cells.
    Always returns the same two columns even when no themes are present
    (otherwise sort_values('n') on an empty DataFrame raises KeyError)."""
    rows = []
    if slice_df is not None and not slice_df.empty:
        for col, label in _REVIEW_THEMES:
            if col in slice_df.columns:
                n = int((slice_df[col].fillna("").astype(str).str.strip() != "").sum())
                if n > 0:
                    rows.append({"theme": label, "n": n})
    if not rows:
        return pd.DataFrame(columns=["theme", "n"])
    return pd.DataFrame(rows).sort_values("n", ascending=False).reset_index(drop=True)


def _sample_quote(slice_df, low_rating=True, max_len=140):
    """Pick a representative review quote from a slice. For "What to fix"
    we want the lowest-rated, most detailed review; for "What to market"
    we want the highest-rated."""
    if slice_df is None or slice_df.empty:
        return ""
    s = slice_df.copy()
    s["_LEN"] = s["REVIEW_TEXT"].fillna("").astype(str).str.len()
    s = s[s["_LEN"] > 20]
    if s.empty:
        return ""
    s = s.sort_values(["RATING", "_LEN"],
                       ascending=[True if low_rating else False, False])
    t = str(s.iloc[0]["REVIEW_TEXT"]).strip()
    if len(t) > max_len:
        t = t[:max_len].rsplit(" ", 1)[0] + "…"
    return t


def _severity(neg_pct, reviews):
    """Severity badge for fix-list cards."""
    n, r = (neg_pct or 0), (reviews or 0)
    if n >= 35 and r >= 30:
        return ("CRITICAL",     "#fff", "#8b1a1a")
    if n >= 25 and r >= 20:
        return ("HIGH PRIORITY","#fff", "#c75c3c")
    if n >= 15:
        return ("WATCH",        "#7a5c00", "#fef3d6")
    return ("MONITOR",          "#7a6a50", "#f0e9d8")


def _strength(pos_pct, reviews, avg_rating):
    """Strength badge for market-list cards."""
    a, p, r = (avg_rating or 0), (pos_pct or 0), (reviews or 0)
    if a >= 4.6 and r >= 50:
        return ("HERO",      "#fff", "#1a7a3e")
    if a >= 4.4 and r >= 30:
        return ("STAR",      "#fff", "#2e8c4f")
    if a >= 4.0 and r >= 20:
        return ("RISING",    "#1a7a3e", "#d6ece1")
    return ("STEADY",        "#7a6a50", "#f0e9d8")


def _star_dist(slice_df):
    """5/4/3/2/1 star counts as a 5-element list (1★ → 5★)."""
    s = slice_df["RATING"].round().clip(1, 5).astype("Int64")
    return [int((s == i).sum()) for i in range(1, 6)]


def render_customer_insights():
    """Customer Insights dashboard — review-based, 6 sub-tabs."""
    st.markdown('<div class="page-title">Customer Insights</div>',
                unsafe_allow_html=True)
    st.markdown(
        '<div class="page-sub">Voice of the customer — pulls from '
        '<code>vahdam_amazon_reviews</code>. '
        'Theme columns are populated by the AI tagger; a review "mentions" a '
        'theme when the cell is non-empty.</div>',
        unsafe_allow_html=True)

    with st.spinner("Loading reviews…"):
        raw = get_reviews_all()
    if raw.empty:
        st.warning("📭 No review rows available.")
        return

    # ── Filters bar ──
    geos     = ["All"] + sorted(g for g in raw["GEO"].dropna().unique() if g)
    brands   = ["All"] + sorted(b for b in raw["BRAND"].dropna().unique() if b)
    cats     = ["All"] + sorted(c for c in raw["CATEGORY"].dropna().unique() if c)
    d_min    = raw["REVIEW_DATE"].min()
    d_max    = raw["REVIEW_DATE"].max()
    if pd.isna(d_min) or pd.isna(d_max):
        d_min, d_max = pd.Timestamp(date.today() - timedelta(days=365)), pd.Timestamp(date.today())

    # Use a custom CSS block to force every widget label in this row to
    # have the SAME height so the inputs themselves stay perfectly aligned
    # even when label text wraps differently.
    st.markdown(
        '<style>'
        'div[data-testid="stHorizontalBlock"] '
        '  [data-testid="stWidgetLabel"] { '
        '    min-height: 20px; line-height: 1.2; }'
        '</style>',
        unsafe_allow_html=True)
    f1, f2, f3, f4, f5, f6, f7 = st.columns([1.2, 1.2, 1.4, 1.4, 1.4, 1.2, 2.0])
    with f1:
        f_geo = st.selectbox("Geography", geos, index=0, key="ci_f_geo")
    with f2:
        f_brand = st.selectbox("Brand", brands, index=0, key="ci_f_brand")
    with f3:
        f_cat = st.selectbox("Category", cats, index=0, key="ci_f_cat")
    with f4:
        f_from = st.date_input("Date from", value=d_min.date(),
                                min_value=d_min.date(), max_value=d_max.date(),
                                key="ci_f_from")
    with f5:
        f_to = st.date_input("Date to", value=d_max.date(),
                              min_value=d_min.date(), max_value=d_max.date(),
                              key="ci_f_to")
    with f6:
        f_min = st.number_input("Min reviews", min_value=0, value=20,
                                  step=5, key="ci_f_min",
                                  help="Minimum reviews per ASIN to be "
                                       "included in Products / Actionables.")
    with f7:
        f_search = st.text_input("Search ASIN or name",
                                  key="ci_f_search",
                                  placeholder="e.g. B07RGK5QKZ / matcha").strip()

    # ── Apply filters ──
    df = raw.copy()
    if f_geo != "All":
        df = df[df["GEO"] == f_geo]
    if f_brand != "All":
        df = df[df["BRAND"] == f_brand]
    if f_cat != "All":
        df = df[df["CATEGORY"] == f_cat]
    df = df[(df["REVIEW_DATE"] >= pd.Timestamp(f_from)) &
            (df["REVIEW_DATE"] <= pd.Timestamp(f_to))]
    if f_search:
        q = f_search.lower()
        df = df[df["ASIN"].str.lower().str.contains(q, na=False) |
                df["PRODUCT_NAME"].fillna("").str.lower().str.contains(q, na=False)]

    # ── ASIN-level cohort (used by several tabs) ──
    if df.empty:
        st.info("📭 No reviews match the current filters.")
        return

    asin_grp = df.groupby(["ASIN", "PRODUCT_NAME", "BRAND", "CATEGORY"],
                          dropna=False).agg(
        REVIEWS  = ("RATING",   "count"),
        AVG_RAT  = ("RATING",   "mean"),
        NEG      = ("NEGATIVE", "sum"),
        NEU      = ("NEUTRAL",  "sum"),
        POS      = ("POSITIVE", "sum"),
    ).reset_index()
    asin_grp["NEG_PCT"] = asin_grp["NEG"] / asin_grp["REVIEWS"] * 100
    asin_grp["POS_PCT"] = asin_grp["POS"] / asin_grp["REVIEWS"] * 100
    asin_min = asin_grp[asin_grp["REVIEWS"] >= f_min].copy()

    st.caption(
        f"**{len(df):,}** reviews · **{asin_grp['ASIN'].nunique():,}** ASINs total · "
        f"**{len(asin_min):,}** ASINs with ≥ {f_min} reviews."
    )

    # ── Sub-tabs ──
    t_over, t_act, t_prod, t_cat, t_geo, t_explorer = st.tabs(
        ["📊 Overview", "🎯 Actionables", "📦 Products",
         "🗂 Categories", "🌍 Geographies", "🔎 Review Explorer"])

    # ─────────────────────────── 1. OVERVIEW ───────────────────────────
    with t_over:
        n_tot = len(df)
        avg   = float(df["RATING"].mean()) if n_tot else 0.0
        n_neg = int(df["NEGATIVE"].sum())
        n_neu = int(df["NEUTRAL"].sum())
        n_pos = int(df["POSITIVE"].sum())
        pct = lambda x: (x / n_tot * 100) if n_tot else 0.0

        cards = [
            ("Reviews",    f"{n_tot:,}",
                f"{asin_grp['ASIN'].nunique():,} products"),
            ("Avg Rating", f"{avg:.2f}/5", "across all reviews"),
            ("Negative %", f"{pct(n_neg):.1f}%",
                f"{n_neg:,} reviews 1–2★"),
            ("Positive %", f"{pct(n_pos):.0f}%",
                f"{n_pos:,} reviews 4–5★"),
            ("Neutral 3★", f"{n_neu:,}",  "opportunity to convert"),
        ]
        cols = st.columns(5, gap="small")
        for col, (lbl, val, sub) in zip(cols, cards):
            col.markdown(strip_card(lbl, val, sub), unsafe_allow_html=True)

        st.markdown('<div class="kpi-row-gap"></div>', unsafe_allow_html=True)

        # Two rows of charts: distribution + monthly trend ; by geo + top themes
        c1, c2 = st.columns(2, gap="medium")
        with c1:
            st.markdown('<div class="section-hdr">Rating Distribution</div>',
                         unsafe_allow_html=True)
            dist = _star_dist(df)
            if HAS_PLOTLY:
                fig = go.Figure(go.Bar(
                    x=["1★", "2★", "3★", "4★", "5★"], y=dist,
                    marker_color=["#8b1a1a","#c75c3c","#d6b54a","#7faa6e","#1a7a3e"]))
                fig.update_layout(plot_bgcolor="#FBF5EA", paper_bgcolor="#FBF5EA",
                                  height=300, margin=dict(l=30, r=20, t=20, b=30))
                fig.update_xaxes(showgrid=False)
                fig.update_yaxes(gridcolor="rgba(171,135,67,0.18)")
                st.plotly_chart(fig, use_container_width=True,
                                 config={"displayModeBar": False})
        with c2:
            st.markdown('<div class="section-hdr">Monthly Trend — '
                         'Reviews &amp; Avg Rating</div>', unsafe_allow_html=True)
            monthly = df.groupby("YEAR_MONTH").agg(
                REVIEWS=("RATING","count"), AVG=("RATING","mean")
            ).reset_index().sort_values("YEAR_MONTH")
            if HAS_PLOTLY and not monthly.empty:
                fig = go.Figure()
                fig.add_trace(go.Bar(x=monthly["YEAR_MONTH"], y=monthly["REVIEWS"],
                                       name="Reviews", marker_color="#AB8743",
                                       yaxis="y"))
                fig.add_trace(go.Scatter(x=monthly["YEAR_MONTH"], y=monthly["AVG"],
                                          name="Avg rating", mode="lines+markers",
                                          line=dict(color="#004A2B", width=2),
                                          yaxis="y2"))
                fig.update_layout(
                    plot_bgcolor="#FBF5EA", paper_bgcolor="#FBF5EA",
                    height=300, margin=dict(l=30, r=20, t=20, b=30),
                    yaxis=dict(title="Reviews",
                                gridcolor="rgba(171,135,67,0.18)"),
                    yaxis2=dict(title="Avg ★", overlaying="y", side="right",
                                  range=[1, 5]),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                  x=0.5, xanchor="center"))
                st.plotly_chart(fig, use_container_width=True,
                                 config={"displayModeBar": False})

        c3, c4 = st.columns(2, gap="medium")
        with c3:
            st.markdown('<div class="section-hdr">By Geography</div>',
                         unsafe_allow_html=True)
            by_geo = df.groupby("GEO").agg(
                AVG=("RATING","mean"),
                NEG_PCT=("NEGATIVE", lambda s: float(s.mean()) * 100),
                N=("RATING","count")).reset_index()
            by_geo = by_geo.sort_values("N", ascending=False)
            if HAS_PLOTLY and not by_geo.empty:
                fig = go.Figure()
                fig.add_trace(go.Bar(x=by_geo["GEO"], y=by_geo["AVG"],
                                       name="Avg ★", marker_color="#AB8743"))
                fig.add_trace(go.Scatter(x=by_geo["GEO"], y=by_geo["NEG_PCT"],
                                          name="% 1-2★", mode="lines+markers",
                                          line=dict(color="#8b1a1a", width=2),
                                          yaxis="y2"))
                fig.update_layout(
                    plot_bgcolor="#FBF5EA", paper_bgcolor="#FBF5EA",
                    height=300, margin=dict(l=30, r=20, t=20, b=30),
                    yaxis=dict(title="Avg ★", range=[0, 5],
                                gridcolor="rgba(171,135,67,0.18)"),
                    yaxis2=dict(title="% 1-2★", overlaying="y", side="right",
                                  range=[0, 50]),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                  x=0.5, xanchor="center"))
                st.plotly_chart(fig, use_container_width=True,
                                 config={"displayModeBar": False})
        with c4:
            st.markdown('<div class="section-hdr">Top complaint themes</div>',
                         unsafe_allow_html=True)
            st.caption("Among 1–2★ reviews")
            t = _theme_counts(df[df["NEGATIVE"]])
            if HAS_PLOTLY and not t.empty:
                t = t.head(12).iloc[::-1]
                fig = go.Figure(go.Bar(x=t["n"], y=t["theme"], orientation="h",
                                         marker_color="#c75c3c"))
                fig.update_layout(plot_bgcolor="#FBF5EA",
                                    paper_bgcolor="#FBF5EA",
                                    height=300, margin=dict(l=120, r=20, t=10, b=30))
                fig.update_xaxes(gridcolor="rgba(171,135,67,0.18)")
                st.plotly_chart(fig, use_container_width=True,
                                 config={"displayModeBar": False})

    # ─────────────────────────── 2. ACTIONABLES ───────────────────────────
    with t_act:
        st.markdown(
            '<div class="page-sub">Data-driven priorities. <b>What to fix</b> '
            'ranks by negative % × √reviews (so high-volume SKUs surface even '
            'when % isn\'t extreme). <b>What to market</b> uses avg ★ × √reviews '
            'to highlight high-performing SKUs with enough volume to back the claim. '
            'Each card shows top complaint/praise themes and the most informative '
            'customer quote.</div>', unsafe_allow_html=True)

        if asin_min.empty:
            st.markdown('<div class="ci-empty">'
                         f'No ASINs meet the ≥ {f_min} review threshold. '
                         f'Lower the filter to populate Actionables.</div>',
                         unsafe_allow_html=True)
        else:
            # Priority scores — sqrt(volume) prevents niche micro-SKUs from
            # dominating the list when their % looks extreme on tiny n.
            asin_rank = asin_min.copy()
            asin_rank["FIX_SCORE"] = asin_rank["NEG_PCT"] * (asin_rank["REVIEWS"] ** 0.5)
            asin_rank["WIN_SCORE"] = asin_rank["AVG_RAT"] * (asin_rank["REVIEWS"] ** 0.5)
            fix_list = asin_rank.sort_values("FIX_SCORE", ascending=False).head(12)
            win_list = asin_rank[asin_rank["AVG_RAT"] >= 4.0] \
                          .sort_values("WIN_SCORE", ascending=False).head(12)

            def _theme_chips(top_themes, polarity):
                if top_themes is None or top_themes.empty:
                    return ""
                cls = "ci-chip-neg" if polarity == "neg" else "ci-chip-pos"
                chips = []
                for _, row in top_themes.head(3).iterrows():
                    chips.append(
                        f'<span class="ci-chip {cls}">{row["theme"]}'
                        f' <span class="ci-chip-count">{int(row["n"])}</span></span>'
                    )
                return f'<div class="ci-themes">{"".join(chips)}</div>'

            def _card(r, polarity, badge, sample):
                # polarity: "neg" for fix-list, "pos" for win-list
                card_cls   = "ci-fix" if polarity == "neg" else "ci-win"
                stat_color = "#8b1a1a" if polarity == "neg" else "#1a7a3e"
                pct_label  = (f"<b>{r['NEG_PCT']:.0f}% neg</b> "
                              f"({int(r['NEG'])} of {int(r['REVIEWS'])} 1–2★)"
                              if polarity == "neg" else
                              f"<b>{r['POS_PCT']:.0f}% pos</b> "
                              f"({int(r['POS'])} of {int(r['REVIEWS'])} 4–5★)")
                top_neg = _theme_counts(df[(df["ASIN"] == r["ASIN"]) & df["NEGATIVE"]])
                top_pos = _theme_counts(df[(df["ASIN"] == r["ASIN"]) & df["POSITIVE"]])
                chips = (_theme_chips(top_neg, "neg") if polarity == "neg"
                         else _theme_chips(top_pos, "pos"))
                badge_label, badge_fg, badge_bg = badge
                title = (r["PRODUCT_NAME"] or "").strip() or r["ASIN"]
                if len(title) > 75:
                    title = title[:72] + "…"
                cats = []
                if r.get("BRAND"):    cats.append(str(r["BRAND"]))
                if r.get("CATEGORY"): cats.append(str(r["CATEGORY"]))
                meta = " · ".join(cats) if cats else ""
                quote_html = (f'<div class="ci-quote">{sample}</div>'
                              if sample else "")
                meta_html = (f'<div class="ci-stats" '
                             f'style="font-size:10.5px;color:#7a6a50;'
                             f'margin-top:0;">{meta}</div>' if meta else "")
                return (
                    f'<div class="ci-card {card_cls}">'
                    f'  <div class="ci-card-head">'
                    f'    <span class="ci-badge" style="background:{badge_bg};'
                    f'color:{badge_fg};">{badge_label}</span>'
                    f'    <span class="ci-title">{title} '
                    f'<span class="ci-asin">· {r["ASIN"]}</span></span>'
                    f'  </div>'
                    f'  {meta_html}'
                    f'  <div class="ci-stats">'
                    f'    <b>{int(r["REVIEWS"]):,}</b> reviews · avg '
                    f'<b style="color:{stat_color};">{r["AVG_RAT"]:.2f}★</b> · '
                    f'{pct_label}'
                    f'  </div>'
                    f'  {chips}'
                    f'  {quote_html}'
                    f'</div>'
                )

            colA, colB = st.columns(2, gap="medium")
            with colA:
                st.markdown(
                    '<div class="section-hdr" style="border-left-color:#8b1a1a;">'
                    'What to fix · highest priority</div>',
                    unsafe_allow_html=True)
                for _, r in fix_list.iterrows():
                    badge  = _severity(r["NEG_PCT"], r["REVIEWS"])
                    sample = _sample_quote(
                        df[(df["ASIN"] == r["ASIN"]) & df["NEGATIVE"]],
                        low_rating=True)
                    st.markdown(_card(r, "neg", badge, sample),
                                 unsafe_allow_html=True)
            with colB:
                st.markdown(
                    '<div class="section-hdr" style="border-left-color:#1a7a3e;">'
                    'What to market · loudest wins</div>',
                    unsafe_allow_html=True)
                if win_list.empty:
                    st.markdown('<div class="ci-empty">'
                                 'No ASINs with ≥4★ avg meet the volume threshold yet.'
                                 '</div>', unsafe_allow_html=True)
                else:
                    for _, r in win_list.iterrows():
                        badge  = _strength(r["POS_PCT"], r["REVIEWS"], r["AVG_RAT"])
                        sample = _sample_quote(
                            df[(df["ASIN"] == r["ASIN"]) & df["POSITIVE"]],
                            low_rating=False)
                        st.markdown(_card(r, "pos", badge, sample),
                                     unsafe_allow_html=True)

    # ─────────────────────────── 3. PRODUCTS ───────────────────────────
    with t_prod:
        st.markdown('<div class="section-hdr">All Products</div>',
                     unsafe_allow_html=True)
        st.caption("Click a row to see review samples + theme breakdown.")
        # Build display table
        prod = asin_min.sort_values("REVIEWS", ascending=False).copy()
        # Per-ASIN top negative themes
        def _top_neg(asin):
            return _theme_counts(df[(df["ASIN"] == asin) & (df["NEGATIVE"])]).head(3)
        prod["TOP_NEG"] = prod["ASIN"].apply(
            lambda a: ", ".join(f"{r['theme']} {r['n']}"
                                for _, r in _top_neg(a).iterrows()) or "—")
        show = pd.DataFrame({
            "ASIN":          prod["ASIN"],
            "Product":       prod["PRODUCT_NAME"].fillna("").str.slice(0, 60),
            "Brand":         prod["BRAND"].fillna("—"),
            "Category":      prod["CATEGORY"].fillna("—"),
            "Reviews":       prod["REVIEWS"].astype(int),
            "Avg ★":         prod["AVG_RAT"].round(2),
            "Neg %":         prod["NEG_PCT"].round(1),
            "Top Neg Themes":prod["TOP_NEG"],
        }).reset_index(drop=True)
        _neg = pd.to_numeric(show["Neg %"], errors="coerce").reset_index(drop=True)
        _avg = pd.to_numeric(show["Avg ★"], errors="coerce").reset_index(drop=True)
        def _style_prod(row):
            s = [""] * len(row)
            idx = row.index.tolist()
            v = _f(_avg.iloc[row.name])
            if v is not None:
                s[idx.index("Avg ★")] = (
                    "color:#004A2B;font-weight:700" if v >= 4.5 else
                    "color:#7a5c00;font-weight:700" if v >= 3.5 else
                    "color:#8b1a1a;font-weight:700")
            n = _f(_neg.iloc[row.name])
            if n is not None:
                s[idx.index("Neg %")] = (
                    "color:#8b1a1a;font-weight:700" if n >= 30 else
                    "color:#7a5c00;font-weight:700" if n >= 15 else
                    "color:#1a7a3e;font-weight:700")
            return s
        st.dataframe(show.style.apply(_style_prod, axis=1).hide(axis="index"),
                     use_container_width=True, height=540,
                     column_config={
                         "Reviews": st.column_config.NumberColumn(format="%,d"),
                         "Avg ★":   st.column_config.NumberColumn(format="%.2f"),
                         "Neg %":   st.column_config.NumberColumn(format="%.1f%%"),
                     })

    # ─────────────────────────── 4. CATEGORIES ───────────────────────────
    with t_cat:
        st.markdown('<div class="section-hdr">By Category</div>',
                     unsafe_allow_html=True)
        cat_g = df.groupby(df["CATEGORY"].fillna("—")).agg(
            REVIEWS=("RATING","count"),
            AVG=("RATING","mean"),
            NEG=("NEGATIVE","sum"),
            POS=("POSITIVE","sum"),
        ).reset_index().rename(columns={"CATEGORY":"Category"})
        cat_g["Neg %"]    = cat_g["NEG"] / cat_g["REVIEWS"] * 100
        cat_g["Pos %"]    = cat_g["POS"] / cat_g["REVIEWS"] * 100
        cat_g = cat_g.sort_values("REVIEWS", ascending=False)

        def _top_for(slice_filter, top_label, n=3):
            sub = df[slice_filter]
            t   = _theme_counts(sub).head(n)
            return ", ".join(f"{r['theme']} {r['n']}" for _, r in t.iterrows()) or "—"
        cat_g["Top Complaints"] = cat_g["Category"].apply(
            lambda c: _top_for((df["CATEGORY"].fillna("—") == c) & df["NEGATIVE"],
                                "complaints"))
        cat_g["Top Praise"]     = cat_g["Category"].apply(
            lambda c: _top_for((df["CATEGORY"].fillna("—") == c) & df["POSITIVE"],
                                "praise"))

        show = pd.DataFrame({
            "Category":       cat_g["Category"],
            "Reviews":        cat_g["REVIEWS"].astype(int),
            "Avg ★":          cat_g["AVG"].round(2),
            "Neg %":          cat_g["Neg %"].round(1),
            "Pos %":          cat_g["Pos %"].round(1),
            "Top Complaints": cat_g["Top Complaints"],
            "Top Praise":     cat_g["Top Praise"],
        }).reset_index(drop=True)
        st.dataframe(show, use_container_width=True, height=540,
                     hide_index=True,
                     column_config={
                         "Reviews": st.column_config.NumberColumn(format="%,d"),
                         "Avg ★":   st.column_config.NumberColumn(format="%.2f"),
                         "Neg %":   st.column_config.NumberColumn(format="%.1f%%"),
                         "Pos %":   st.column_config.NumberColumn(format="%.1f%%"),
                     })

    # ─────────────────────────── 5. GEOGRAPHIES ───────────────────────────
    with t_geo:
        st.markdown('<div class="section-hdr">By Geography</div>',
                     unsafe_allow_html=True)
        geo_g = df.groupby("GEO").agg(
            REVIEWS=("RATING","count"),
            ASINS=("ASIN","nunique"),
            AVG=("RATING","mean"),
            NEG=("NEGATIVE","sum"),
            POS=("POSITIVE","sum"),
        ).reset_index().rename(columns={"GEO":"Geo"})
        geo_g["Neg %"] = geo_g["NEG"] / geo_g["REVIEWS"] * 100
        geo_g["Pos %"] = geo_g["POS"] / geo_g["REVIEWS"] * 100
        geo_g = geo_g.sort_values("REVIEWS", ascending=False)
        geo_g["Top Complaints"] = geo_g["Geo"].apply(
            lambda g: ", ".join(f"{r['theme']} {r['n']}"
                                  for _, r in _theme_counts(
                                      df[(df["GEO"] == g) & df["NEGATIVE"]]
                                  ).head(3).iterrows()) or "—")
        geo_g["Top Praise"] = geo_g["Geo"].apply(
            lambda g: ", ".join(f"{r['theme']} {r['n']}"
                                  for _, r in _theme_counts(
                                      df[(df["GEO"] == g) & df["POSITIVE"]]
                                  ).head(3).iterrows()) or "—")

        show_g = pd.DataFrame({
            "Geo":             geo_g["Geo"],
            "Reviews":         geo_g["REVIEWS"].astype(int),
            "ASINs":           geo_g["ASINS"].astype(int),
            "Avg ★":           geo_g["AVG"].round(2),
            "Neg %":           geo_g["Neg %"].round(1),
            "Pos %":           geo_g["Pos %"].round(1),
            "Top Complaints":  geo_g["Top Complaints"],
            "Top Praise":      geo_g["Top Praise"],
        }).reset_index(drop=True)
        st.dataframe(show_g, use_container_width=True, height=400,
                     hide_index=True,
                     column_config={
                         "Reviews": st.column_config.NumberColumn(format="%,d"),
                         "ASINs":   st.column_config.NumberColumn(format="%,d"),
                         "Avg ★":   st.column_config.NumberColumn(format="%.2f"),
                         "Neg %":   st.column_config.NumberColumn(format="%.1f%%"),
                         "Pos %":   st.column_config.NumberColumn(format="%.1f%%"),
                     })

    # ─────────────────────────── 6. REVIEW EXPLORER ───────────────────────────
    with t_explorer:
        st.markdown('<div class="section-hdr">Individual Reviews</div>',
                     unsafe_allow_html=True)
        rc1, rc2, rc3 = st.columns([1.5, 1.5, 5])
        with rc1:
            rating_filter = st.multiselect("Star rating", [1, 2, 3, 4, 5],
                                             default=[1, 2],
                                             key="ci_rev_rating")
        with rc2:
            theme_opts = ["(any)"] + [lbl for _, lbl in _REVIEW_THEMES]
            theme_pick = st.selectbox("Mentions theme", theme_opts, index=0,
                                       key="ci_rev_theme")
        with rc3:
            kw = st.text_input("Keyword in review text",
                                 key="ci_rev_kw",
                                 placeholder="e.g. bitter, packaging, leak").strip()

        rev_df = df.copy()
        if rating_filter:
            rev_df = rev_df[rev_df["RATING"].round().isin(rating_filter)]
        if theme_pick != "(any)":
            for col, lbl in _REVIEW_THEMES:
                if lbl == theme_pick:
                    rev_df = rev_df[rev_df[col].fillna("").astype(str).str.strip() != ""]
                    break
        if kw:
            rev_df = rev_df[
                rev_df["REVIEW_TEXT"].fillna("").str.contains(kw, case=False, na=False) |
                rev_df["REVIEW_TITLE"].fillna("").str.contains(kw, case=False, na=False)]
        st.caption(f"**{len(rev_df):,}** matching reviews.")
        rev_df = rev_df.sort_values("REVIEW_DATE", ascending=False).head(500)
        rev_show = pd.DataFrame({
            "Date":     rev_df["REVIEW_DATE"].dt.strftime("%Y-%m-%d"),
            "Geo":      rev_df["GEO"],
            "ASIN":     rev_df["ASIN"],
            "Product":  rev_df["PRODUCT_NAME"].fillna("").str.slice(0, 60),
            "Rating":   rev_df["RATING"].round(1),
            "Title":    rev_df["REVIEW_TITLE"].fillna("").str.slice(0, 80),
            "Review":   rev_df["REVIEW_TEXT"].fillna("").str.slice(0, 200),
        })
        st.dataframe(rev_show, use_container_width=True, height=600,
                     hide_index=True,
                     column_config={
                         "Rating": st.column_config.NumberColumn(format="%.1f ★"),
                     })


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
elif view == "customer_insights":
    render_customer_insights()
else:
    render_asin()
