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
    )

@st.cache_data(ttl=300, show_spinner="Loading data…")
def run_query(sql: str) -> pd.DataFrame:
    cur = get_conn().cursor()
    cur.execute(sql)
    return cur.fetch_pandas_all()

# ── Session state ─────────────────────────────────────────────────────────────
for k, v in [("view","overview"), ("selected_geo",None), ("selected_subcat",None)]:
    if k not in st.session_state: st.session_state[k] = v

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
    f_channel = st.multiselect("Channel",      sorted(opts["CHANNEL"].dropna().unique()),
                               key="flt_channel")
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

# ── WHERE builder ─────────────────────────────────────────────────────────────
def build_where(geo_override=None, subcat_override=None, date_from=None, date_to=None,
                extra_filters=None):
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
def render_overview():
    st.markdown('<div class="page-title">Amazon P&amp;L Overview</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="page-sub">{d_from.strftime("%d %b %Y")} &rarr; {d_to.strftime("%d %b %Y")} '
        f'&nbsp;&bull;&nbsp; Currency: {"INR (₹)" if use_inr else "Local"} '
        f'&nbsp;&bull;&nbsp; Pace: {days_elapsed}/{_total_days} days elapsed</div>',
        unsafe_allow_html=True)

    where    = build_where()
    where_fm = build_where(date_from=month_start, date_to=month_end)
    kpi      = get_kpis(where, sfx)

    if kpi.empty:
        st.warning("📭 No data found for the selected filters. Try widening the date range or clearing some filters.")
        return
    k = kpi.iloc[0]

    # ── KPI Cards ──
    cols = st.columns(5)
    cards = [
        ("Revenue vs Budget",  fmt_lakhs(k["SALES_ACT"]), f"Bud: {fmt_lakhs(k['SALES_BUD'])}", k["REV_PCT"],
         kpi_delta(k["REV_DELTA"])),
        ("CM1% vs Budget",     fmt_pct(k["CM1_ACT"]),    f"Bud: {fmt_pct(k['CM1_BUD'])}",     None,
         kpi_delta(k["CM1_DELTA"], unit="pp")),
        ("ACoS%",              fmt_pct(k["ACOS_ACT"]),   f"Bud: {fmt_pct(k['ACOS_BUD'])}",    None,
         kpi_delta(k["ACOS_DELTA"], unit="pp", invert=True)),
        ("CM2%",               fmt_pct(k["CM2_ACT"]),    f"Bud: {fmt_pct(k['CM2_BUD'])}",     None,
         kpi_delta(k["CM2_DELTA"], unit="pp")),
        ("CM2 Absolute",       fmt_lakhs(k["CM2_ABS_ACT"]), f"Bud: {fmt_lakhs(k['CM2_ABS_BUD'])}", None,
         kpi_delta(k["CM2_ABS_DELTA"])),
    ]
    for col, (label, actual, budget, pct, delta) in zip(cols, cards):
        badge = pct_badge(pct) if pct is not None else ""
        col.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-label">{label}</div>
            <div class="kpi-actual">{actual}</div>
            <div class="kpi-budget">{budget}</div>
            {delta}
            {badge}
        </div>""", unsafe_allow_html=True)

    st.markdown('<div class="section-hdr">GEO &times; Channel Breakdown</div>', unsafe_allow_html=True)
    st.caption(f"Pro-rata pace: {days_elapsed} of {_total_days} days elapsed this month  "
               f"|  💡 Click a **GEO TOTAL** row to drill into sub-categories")

    df    = get_view1(where, sfx)
    fm_df = get_fm_budget_v1(where_fm, sfx)

    if df.empty:
        st.info("📭 No data available for the current selection.")
        return

    df = df.merge(fm_df[["GEO","CHANNEL","FM_SALES_BUD","FM_CM2_BUD"]],
                  on=["GEO","CHANNEL"], how="left")

    disp = df.copy()
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

    dcols = ["GEO","CHANNEL","Qty","Revenue Act","Revenue Bud","Rev % Achvd","Rev vs Plan",
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
        key="overview_table")

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
        st.markdown(
            f'<div class="breadcrumb">Overview &rsaquo; {geo}</div>'
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
        st.markdown(
            f'<div class="breadcrumb">Overview &rsaquo; {geo} &rsaquo; {subcat}</div>'
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

    # ── Tabs ──
    tab_pnl, tab_ads, tab_chart = st.tabs(
        ["📊 P&L vs Budget", "📣 Ad Performance", "🫧 Bubble Chart"])

    # ── Tab 1: P&L ──
    with tab_pnl:
        st.caption("All budget figures from P&L table for the same date range. Actuals = total sales (organic + paid).")
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

                fig = px.scatter(
                    chart_df.dropna(subset=["_acos","_impr"]),
                    x="_impr",
                    y="_acos",
                    size="_spend_size",
                    color="_cm2",
                    color_continuous_scale=[[0,"#fde8e8"],[0.4,"#fef3d6"],[1,"#d6ece1"]],
                    hover_name="_name_short",
                    custom_data=["ASIN","_rev_fmt","_bud_rev_fmt","_rev_achvd",
                                 "_spend_fmt","_ctr_fmt","_conv_fmt","_paid_pct",
                                 "ACT_UNITS","ACT_CM1_PCT","ACT_CM2_PCT","BUD_CM2_PCT"],
                    size_max=60,
                    labels={"_impr":"Impressions","_acos":"ACoS%","_cm2":"CM2%"},
                    title=f"ASIN Performance — {geo} / {subcat}  |  Bubble size = Ad Spend  |  Color = CM2%"
                )
                fig.update_traces(
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
                    coloraxis_colorbar=dict(title="CM2%", ticksuffix="%"),
                    xaxis_title="Impressions",
                    yaxis_title="ACoS%",
                    height=520,
                    margin=dict(l=40, r=40, t=60, b=40),
                )
                fig.add_hline(y=20, line_dash="dot", line_color="#004A2B", opacity=0.4,
                              annotation_text="ACoS 20%", annotation_position="right")
                fig.add_hline(y=35, line_dash="dot", line_color="#AB8743", opacity=0.4,
                              annotation_text="ACoS 35%", annotation_position="right")
                st.plotly_chart(fig, use_container_width=True)
                st.caption("Green zone: ACoS < 20% (efficient)  |  Amber: 20–35%  |  Red: > 35%  |  Larger bubbles = higher spend")


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

    t1, t2, t3 = st.tabs(["📊 P&L Statement", "📈 Daily Trend", "🗂️ By Category"])

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

    # ── Tab 3: By Category ──
    with t3:
        with st.spinner("Loading category P&L…"):
            cat = get_pnl_category(where, sfx)
        if cat.empty:
            st.info("📭 No category data available.")
        else:
            disp = cat.copy()
            col_map = [("SALES_ACT","Sales Act"), ("SALES_BUD","Sales Bud"),
                       ("CM1_ACT","CM1 Act"), ("CM2_ACT","CM2 Act"),
                       ("PM_SPEND_ACT","PM Spend")]
            for src, lbl in col_map:
                if src in disp.columns:
                    disp[lbl] = disp[src].apply(fmt_lakhs)

            # % of Total Sales (excluding Grand Total)
            _of_total_n = None
            if "SALES_ACT" in disp.columns:
                _sales_num = pd.to_numeric(disp["SALES_ACT"], errors="coerce")
                _gt_mask   = disp["CATEGORY"] == "GRAND TOTAL"
                _gt_val    = _sales_num[_gt_mask].iloc[0] if _gt_mask.any() else _sales_num.sum()
                _of_total_n = (_sales_num / _gt_val * 100).reset_index(drop=True)
                disp["% of Total"] = _of_total_n.apply(fmt_pct)

            if "SALES_ACT" in disp.columns and "SALES_BUD" in disp.columns:
                _rev_n = (pd.to_numeric(disp["SALES_ACT"], errors="coerce") /
                          pd.to_numeric(disp["SALES_BUD"], errors="coerce") * 100
                         ).reset_index(drop=True)
                disp["Rev %"] = _rev_n.apply(fmt_pct)
            else:
                _rev_n = None

            labels  = [lbl for src, lbl in col_map if src in disp.columns]
            show_c  = ["CATEGORY"] + labels
            if "% of Total" in disp.columns: show_c.append("% of Total")
            if "Rev %"      in disp.columns: show_c.append("Rev %")
            ct      = disp[show_c].rename(columns={"CATEGORY": "Category"}).reset_index(drop=True)

            def style_cat(row):
                s   = [""] * len(row)
                idx = row.index.tolist()
                if "Rev %" in idx and _rev_n is not None:
                    s[idx.index("Rev %")] = color_pct(_rev_n.iloc[row.name])
                if row.get("Category") == "GRAND TOTAL":
                    s = [(x + TOTAL_ROW).lstrip(";") for x in s]
                return s

            st.markdown('<div class="section-hdr">Category P&amp;L</div>',
                        unsafe_allow_html=True)
            st.dataframe(ct.style.apply(style_cat, axis=1).hide(axis="index"),
                         use_container_width=True, height=420)
            _cl1, _cl2 = st.columns([6, 1])
            with _cl1:
                st.caption("% of Total = share of Grand Total Sales (Actual). "
                           "Rev % = Sales Actual ÷ Sales Budget.")
            with _cl2:
                st.download_button("📥 CSV", ct.to_csv(index=False).encode("utf-8"),
                    file_name=f"pnl_category_{d_from}_{d_to}.csv",
                    mime="text/csv", use_container_width=True, key="dl_pnl_cat")


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
if view == "overview":
    render_overview()
elif view == "subcategory":
    render_subcategory()
elif view == "pnl":
    render_pnl()
else:
    render_asin()
