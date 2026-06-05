"""
D2C UK dashboard — integrated into the main Vahdam dashboard as the
**D2C → UK** view. Entry point: ``render(run_query)``.

This module wraps the user's monolithic D2C UK source file
(``streamlit_app_v3.py`` by Yakshit Bansal, May 2026) so it can run
against the dashboard's shared Snowflake connection without changes
to that source file.

Adapter trick
-------------
The user's code uses the Snowpark-style API:
    df = session.sql(sql).to_pandas()
The main dashboard exposes a different helper:
    df = run_query(sql)
The ``_D2CSession`` adapter below exposes a ``.sql(...).to_pandas()``
shape that delegates to ``run_query``, so the user's queries run
unchanged.

The only edits applied to the source body:
  * Module-level execution is wrapped inside ``render(run_query)``.
  * ``st.set_page_config(...)`` is dropped (dashboard already configures
    the page).
  * The user's ``st.title(...)`` + static caption + ``**Currency:** GBP``
    markdown are replaced with the dashboard's ``page-title`` /
    ``page-sub`` chrome.
  * ``conn = st.connection(...); session = conn.session()`` is replaced
    with ``session = _D2CSession(run_query)``.
  * All ``st.session_state`` keys and Streamlit widget ``key=`` values
    are prefixed with ``d2c_uk_`` to avoid collisions with the Amazon
    sidebar's date-preset state.
"""
import streamlit as st
import os
import calendar
from datetime import datetime, timedelta

import pandas as pd
from dateutil.relativedelta import relativedelta


# ─── Session adapter ─────────────────────────────────────────────────────
class _D2CSqlResult:
    """The user's code calls ``.to_pandas()`` on the result of
    ``session.sql(...)``. We expose that single method and delegate
    to ``run_query``."""
    def __init__(self, run_query, sql):
        self._run_query = run_query
        self._sql = sql

    def to_pandas(self):
        return self._run_query(self._sql)


class _D2CSession:
    """Replace the user's ``conn.session()`` Snowpark Session with a
    minimal duck-typed object that supports ``session.sql(...)`` and
    delegates execution to the dashboard's ``run_query``."""
    def __init__(self, run_query):
        self._run_query = run_query

    def sql(self, sql):
        return _D2CSqlResult(self._run_query, sql)


# ─── D2C UK theme — beige palette from the user's source ─────────────────
_D2C_UK_CSS = """
<style>
.beige-table {
    width: 100%; border-collapse: separate; border-spacing: 0;
    background: rgba(255, 250, 235, 0.85); border-radius: 12px; overflow: hidden;
    border: 1px solid #c9a66b; font-family: 'Helvetica', sans-serif; font-size: 13px;
    box-shadow: 0 4px 14px rgba(120, 80, 30, 0.10); margin: 8px 0 18px 0;
}
.beige-table th {
    background: linear-gradient(180deg, #b58a4b 0%, #8b5a2b 100%);
    color: #fff8e8; padding: 10px 12px; text-align: left;
    font-weight: 600; letter-spacing: 0.3px; border-bottom: 2px solid #6b3f17;
}
.beige-table th.selected-col { background: linear-gradient(180deg, #d4a04a 0%, #b07418 100%); }
.beige-table td {
    padding: 9px 12px; border-bottom: 1px solid #ead9b5;
    color: #3e2f1c; vertical-align: middle;
}
.beige-table tr:nth-child(even) td { background: rgba(245, 235, 210, 0.45); }
.beige-table tr:hover td { background: rgba(212, 160, 74, 0.18); transition: background 0.2s ease; }
.beige-table td.selected-col { background: rgba(212, 160, 74, 0.22) !important; font-weight: 600; }
.beige-table td.metric-name { font-weight: 600; color: #5b3a1b; background: rgba(212, 184, 138, 0.25); }
.delta-up   { color: #1f7a3a !important; font-weight: 600; font-size: 11px; margin-left: 6px; }
.delta-down { color: #b3261e !important; font-weight: 600; font-size: 11px; margin-left: 6px; }
.delta-flat { color: #8a7558 !important; font-weight: 600; font-size: 11px; margin-left: 6px; }
.preset-row { display: flex; gap: 8px; flex-wrap: wrap; margin: 6px 0; }
</style>
"""


# ─── Master query constants (verbatim from user source) ──────────────────
# All Shopify sales/revenue figures use TOTAL_SALES with a coffee tax
# adjustment (PRODUCT_NAME ILIKE '%coffee%' -> x5/6) and exclude refunds
# (IS_REFUND = 0), matching the UK master P&L query.
NET_SALES_EXPR = (
    "CASE WHEN PRODUCT_NAME ILIKE '%coffee%' "
    "THEN TOTAL_SALES * 5.0/6.0 ELSE TOTAL_SALES END"
)
FX_RATE = 121.05            # INR per GBP, matches master query

# Software base is in USD, anchored May 2026 = $5058, +10% per calendar month.
# Converted to GBP via 90.53 INR/USD, then 121.05 INR/GBP.
SOFTWARE_BASE_COST_USD = 5058.0
SOFTWARE_ANCHOR_YEAR   = 2026
SOFTWARE_ANCHOR_MONTH  = 5
SOFTWARE_MOM_GROWTH    = 0.10
USD_TO_INR             = 90.53      # INR per USD

# Loop = 0.7% of subscription net sales (orders tagged 'Billing Cycle'),
# computed on raw TOTAL_SALES (NO coffee ×5/6 adjustment).
LOOP_COMMISSION_RATE   = 0.007

# Per-metric judgement: "up" = higher is better, "down" = lower is better,
# "neutral" = no good/bad colour (targets, or absolute costs that scale with volume).
METRIC_DIRECTION = {
    # higher is better
    "Impressions": "up", "Clicks": "up", "Landing Page": "up", "LPV %": "up",
    "Checkouts": "up", "CTR": "up", "Purchases": "up",
    "Meta Purchase Value": "up", "All New Purchase Value": "up",
    "Total Coffee Purchase Value": "up", "Total Category Purchase Value": "up", "All Revenue": "up",
    "New Purchase ROAS": "up", "NEW+ Purchase ROAS": "up", "Just Meta ROAS": "up",
    "AOV": "up", "New AOV": "up", "CR": "up", "Blended ROAS": "up",
    "Coffee Blended": "up", "Category Blended": "up", "Sub Retention Revenue": "up",
    "Net Sales (After Tax)": "up", "Gross Margin": "up", "CM1": "up", "CM2": "up", "CM1 %": "up",
    # lower is better (efficiency / cost ratios)
    "Average CPM": "down", "Average CPC": "down", "Cost Per Checkout": "down", "CPA": "down",
    "COGS %": "down", "Ad Duty %": "down", "Outbound %": "down", "Last Mile %": "down",
    "Storage %": "down", "PG Commission %": "down", "Supply %": "down",
    # neutral (target line + absolute cost lines that scale with revenue)
    "ROAS Wanted": "neutral", "Total Ad Spent": "neutral",
    "COGS": "neutral", "COGS (incl. Duty)": "neutral",
    "Outbound": "neutral", "Last Mile": "neutral", "Last Mile (per-SKU)": "neutral",
    "Storage": "neutral", "PG Commission": "neutral", "Shopify Costs": "neutral",
    "Loop Commission": "neutral", "Performance Marketing Cost": "neutral",
    "Agency Fees": "neutral", "Software & Platform Cost": "neutral",
}


def render(run_query):
    """Entry point called from app.py. Renders the UK D2C dashboard
    using the user's monolithic source via the session adapter."""

    st.markdown(_D2C_UK_CSS, unsafe_allow_html=True)
    st.markdown('<div class="page-title">D2C &mdash; United Kingdom</div>',
                unsafe_allow_html=True)
    snapshot_time = datetime.now().strftime("%d %b %Y · %H:%M:%S")
    st.markdown(
        f'<div class="page-sub">Snapshot {snapshot_time} '
        f'&nbsp;·&nbsp; Currency: <b>GBP (£)</b> '
        f'&nbsp;·&nbsp; Source: Shopify UK + Meta Ads + Google Ads'
        f'</div>',
        unsafe_allow_html=True)

    st.info(
        "The 4 month columns (Jan–Apr 2026) are literal & never change. "
        "The **Selected Range** column at left reflects the date-range "
        "picker below (default: Last 7 Days). Each value's % change "
        "compares it to the **immediately-preceding like period** — the "
        "Selected Range vs the equal-length window just before it (e.g. "
        "Last 7 Days vs the prior 7 days = days 8–14 ago), Month-to-date "
        "vs the same elapsed days of the previous month, and each month "
        "vs the previous month. Green ↑ = increase, red ↓ = decrease. "
        "Cohort LTV + Retention sections below also follow the picker."
    )

    # ── Use the dashboard's run_query via a Snowpark-shaped adapter ──
    session = _D2CSession(run_query)

    yesterday = (datetime.today() - timedelta(days=1)).date()

    # ─── DATE RANGE PICKER (replaces the static "Last 7 Days" column) ─
    st.markdown("### 📅 Date Range")
    _PRESETS = {
        "Last 7 Days":   7,
        "Last 14 Days":  14,
        "Last 30 Days":  30,
        "Last 60 Days":  60,
        "Last 90 Days":  90,
        "Custom":        None,
    }
    if "d2c_uk_selected_preset" not in st.session_state:
        st.session_state.d2c_uk_selected_preset = "Last 7 Days"
    if "d2c_uk_range_from" not in st.session_state:
        st.session_state.d2c_uk_range_from = yesterday - timedelta(days=6)
    if "d2c_uk_range_to" not in st.session_state:
        st.session_state.d2c_uk_range_to = yesterday

    _pr_cols = st.columns(len(_PRESETS))
    for _i, (_lbl, _days) in enumerate(_PRESETS.items()):
        with _pr_cols[_i]:
            if st.button(_lbl, use_container_width=True,
                         type="primary" if st.session_state.d2c_uk_selected_preset == _lbl else "secondary",
                         key=f"d2c_uk_preset_{_lbl}"):
                st.session_state.d2c_uk_selected_preset = _lbl
                if _days is not None:
                    st.session_state.d2c_uk_range_to = yesterday
                    st.session_state.d2c_uk_range_from = yesterday - timedelta(days=_days - 1)
                st.rerun()

    if st.session_state.d2c_uk_selected_preset == "Custom":
        _dc1, _dc2 = st.columns(2)
        with _dc1:
            st.session_state.d2c_uk_range_from = st.date_input("From", value=st.session_state.d2c_uk_range_from, key="d2c_uk_custom_from")
        with _dc2:
            st.session_state.d2c_uk_range_to   = st.date_input("To",   value=st.session_state.d2c_uk_range_to,   key="d2c_uk_custom_to")
        if st.session_state.d2c_uk_range_from > st.session_state.d2c_uk_range_to:
            st.error("'From' must be on or before 'To'.")
            st.stop()

    selected_from = st.session_state.d2c_uk_range_from
    selected_to   = st.session_state.d2c_uk_range_to
    _days_in_range = (selected_to - selected_from).days + 1
    selected_label = f"{st.session_state.d2c_uk_selected_preset} ({selected_from.strftime('%b %d')} → {selected_to.strftime('%b %d')})"
    st.caption(f"📊 Showing **{selected_label}** · {_days_in_range} days")
    st.markdown("---")

    seven_days_ago = selected_from   # picker drives the first column
    current_month_start = yesterday.replace(day=1)
    prev_month_end = current_month_start - timedelta(days=1)
    prev_month_start = prev_month_end.replace(day=1)
    month_minus2_end = prev_month_start - timedelta(days=1)
    month_minus2_start = month_minus2_end.replace(day=1)
    month_minus3_end = month_minus2_start - timedelta(days=1)
    month_minus3_start = month_minus3_end.replace(day=1)

    # ─── COMPARISON WINDOWS (rate-of-change basis) ───────────────────
    # Each column's % change is computed against the immediately-
    # preceding period of equal length / type — NOT the next column over:
    #   • Selected range -> the equal-length window directly before it
    #                       (Last 7 Days -> days 8..14 ago)
    #   • Month TD       -> the same number of elapsed days in the previous month
    #   • Each month col -> the previous calendar month
    #   • Oldest month   -> no prior period (no delta shown)
    _sel_len      = (selected_to - selected_from).days + 1
    _sel_cmp_to   = selected_from - timedelta(days=1)
    _sel_cmp_from = _sel_cmp_to - timedelta(days=_sel_len - 1)

    _mtd_days     = (yesterday - current_month_start).days + 1
    _mtd_cmp_from = prev_month_start
    _mtd_cmp_to   = min(prev_month_start + timedelta(days=_mtd_days - 1), prev_month_end)

    compare_periods = {
        selected_label:                       (_sel_cmp_from, _sel_cmp_to),
        "Month TD":                           (_mtd_cmp_from, _mtd_cmp_to),
        prev_month_start.strftime("%b %Y"):   (month_minus2_start, month_minus2_end),
        month_minus2_start.strftime("%b %Y"): (month_minus3_start, month_minus3_end),
        month_minus3_start.strftime("%b %Y"): None,
    }

    def build_compare_values(value_fn, metric_names_list):
        """value_fn(start, end) -> {metric: value}; returns {col: {metric: cmp_value}}."""
        cv = {}
        for _col, _win in compare_periods.items():
            if _win is None:
                continue
            _d = value_fn(_win[0], _win[1])
            cv[_col] = {m: _d[m] for m in metric_names_list}
        return cv

    # Lower bound must cover the static 3-month window, the selected range, AND the
    # selected range's comparison window (so the Selected-Range delta has data for
    # every preset, including 60/90-day).
    data_lower_bound = min(month_minus3_start, selected_from, _sel_cmp_from)
    month_minus3_start_q = data_lower_bound  # used as the SQL lower bound below

    df_raw = session.sql("""
        SELECT DATE_START, SPEND
        FROM (
            SELECT DATE_START, SPEND
            FROM VAHDAM_DB.MAPLEMONK.META_UK_CUSTOMCAMPAIGNS_DATA
            WHERE DATE_START >= '{lower}' AND DATE_START <= '{yesterday}'
            UNION ALL
            SELECT "segments.date" AS DATE_START, ("metrics.cost_micros" / 1000000.0) * (90.53 / 121.05) AS SPEND
            FROM VAHDAM_DB.MAPLEMONK.GOOGLE_ADS_UK_CAMPAIGN_DATA
            WHERE "segments.date" >= '{lower}' AND "segments.date" <= '{yesterday}'
        )
    """.format(lower=month_minus3_start_q, yesterday=yesterday)).to_pandas()

    df_raw["DATE_START"] = pd.to_datetime(df_raw["DATE_START"]).dt.date

    def sum_spend(df, start, end):
        mask = (df["DATE_START"] >= start) & (df["DATE_START"] <= end)
        return round(df.loc[mask, "SPEND"].sum(), 2)

    # ─── HELPERS for HTML tables with %-change deltas ────────────────
    def _to_num(v):
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            s = v.replace("£", "").replace("$", "").replace(",", "").replace("%", "").strip()
            try: return float(s)
            except: return None
        return None

    def _delta_html(curr, prev, direction="neutral"):
        c, p = _to_num(curr), _to_num(prev)
        if c is None or p is None or p == 0:
            return ""
        pct = (c - p) / abs(p) * 100
        if abs(pct) < 0.05:
            return f"<span class='delta-flat'>● {pct:+.1f}%</span>"
        arrow = "▲" if pct > 0 else "▼"          # factual direction of change
        if direction == "neutral":
            cls = "delta-flat"                    # grey — no good/bad judgement
        else:
            improving = (pct > 0) if direction == "up" else (pct < 0)
            cls = "delta-up" if improving else "delta-down"   # green if good, red if bad
        return f"<span class='{cls}'>{arrow} {pct:+.1f}%</span>"

    def render_beige_table(df, selected_col_name=None, compare_values=None):
        """
        compare_values: optional {col_name: {metric_name: comparison_value}}.
        When provided, each cell's delta is computed vs its explicit comparison
        period. When omitted, falls back to comparing to the next column (older).
        """
        cols = list(df.columns)
        period_cols = [c for c in cols if c != "Metric"]
        html = ["<table class='beige-table'><thead><tr>"]
        html.append("<th>Metric</th>")
        for c in period_cols:
            cls = "selected-col" if c == selected_col_name else ""
            html.append(f"<th class='{cls}'>{c}</th>")
        html.append("</tr></thead><tbody>")
        for _, row in df.iterrows():
            metric = row["Metric"]
            html.append("<tr>")
            html.append(f"<td class='metric-name'>{metric}</td>")
            for i, c in enumerate(period_cols):
                val = row[c]
                if compare_values is not None:
                    prev_val = compare_values.get(c, {}).get(metric)
                else:
                    prev_val = row[period_cols[i + 1]] if i + 1 < len(period_cols) else None
                delta = _delta_html(val, prev_val, METRIC_DIRECTION.get(metric, "neutral")) if prev_val is not None else ""
                cls = "selected-col" if c == selected_col_name else ""
                html.append(f"<td class='{cls}'>{val}{delta}</td>")
            html.append("</tr>")
        html.append("</tbody></table>")
        st.markdown("".join(html), unsafe_allow_html=True)

    metrics_data = {
        "Metric": ["Total Ad Spent"],
        selected_label: [sum_spend(df_raw, seven_days_ago, yesterday)],
        "Month TD": [sum_spend(df_raw, current_month_start, yesterday)],
        prev_month_start.strftime("%b %Y"): [sum_spend(df_raw, prev_month_start, prev_month_end)],
        month_minus2_start.strftime("%b %Y"): [sum_spend(df_raw, month_minus2_start, month_minus2_end)],
        month_minus3_start.strftime("%b %Y"): [sum_spend(df_raw, month_minus3_start, month_minus3_end)],
    }

    df_metrics = pd.DataFrame(metrics_data)

    st.subheader("💰 Metrics Summary")
    metrics_compare = build_compare_values(
        lambda s, e: {"Total Ad Spent": sum_spend(df_raw, s, e)},
        ["Total Ad Spent"],
    )
    render_beige_table(df_metrics, selected_col_name=selected_label, compare_values=metrics_compare)

    st.markdown("### 📈 Performance (Meta, AWAR excluded)")

    df_meta = session.sql("""
        SELECT
            DATE_START,
            IMPRESSIONS,
            INLINE_LINK_CLICKS AS CLICKS,
            SPEND,
            NVL(GET(FILTER(ACTIONS, a -> a:action_type::STRING = 'landing_page_view')[0], 'value')::FLOAT, 0) AS LANDING_PAGE_VIEWS,
            NVL(GET(FILTER(ACTIONS, a -> a:action_type::STRING = 'offsite_conversion.fb_pixel_initiate_checkout')[0], 'value')::FLOAT, 0) AS CHECKOUTS,
            NVL(GET(FILTER(ACTIONS, a -> a:action_type::STRING = 'offsite_conversion.fb_pixel_purchase')[0], 'value')::FLOAT, 0) AS PURCHASES
        FROM VAHDAM_DB.MAPLEMONK.META_UK_CUSTOMCAMPAIGNS_DATA
        WHERE DATE_START >= '{lower}' AND DATE_START <= '{yesterday}'
          AND CAMPAIGN_NAME NOT ILIKE '%AWAR%'
    """.format(lower=month_minus3_start_q, yesterday=yesterday)).to_pandas()

    df_meta["DATE_START"] = pd.to_datetime(df_meta["DATE_START"]).dt.date

    def meta_metrics(df, start, end):
        mask = (df["DATE_START"] >= start) & (df["DATE_START"] <= end)
        subset = df.loc[mask]
        impressions = subset["IMPRESSIONS"].sum()
        clicks = subset["CLICKS"].sum()
        spend = subset["SPEND"].sum()
        lpv = subset["LANDING_PAGE_VIEWS"].sum()
        checkouts = subset["CHECKOUTS"].sum()
        purchases = subset["PURCHASES"].sum()
        lpv_pct = (lpv / clicks * 100) if clicks > 0 else 0
        cpm = (spend / impressions * 1000) if impressions > 0 else 0
        cpc = (spend / clicks) if clicks > 0 else 0
        ctr = (clicks / impressions * 100) if impressions > 0 else 0
        cost_per_checkout = (spend / checkouts) if checkouts > 0 else 0
        cpa = (spend / purchases) if purchases > 0 else 0
        return {
            "Impressions": round(impressions),
            "Clicks": round(clicks),
            "Landing Page": round(lpv),
            "LPV %": f"{lpv_pct:.2f}%",
            "Checkouts": round(checkouts),
            "Average CPM": round(cpm, 2),
            "Average CPC": round(cpc, 2),
            "CTR": f"{ctr:.2f}%",
            "Cost Per Checkout": round(cost_per_checkout, 2),
            "Purchases": round(purchases),
            # "CPA": round(cpa, 2),
        }

    periods = [
        (selected_label, seven_days_ago, yesterday),
        ("Month TD", current_month_start, yesterday),
        (prev_month_start.strftime("%b %Y"), prev_month_start, prev_month_end),
        (month_minus2_start.strftime("%b %Y"), month_minus2_start, month_minus2_end),
        (month_minus3_start.strftime("%b %Y"), month_minus3_start, month_minus3_end),
    ]

    perf_rows = []
    metric_names = ["Impressions", "Clicks", "Landing Page", "LPV %", "Checkouts",
                    "Average CPM", "Average CPC", "CTR", "Cost Per Checkout", "Purchases"]

    period_data = {name: meta_metrics(df_meta, start, end) for name, start, end in periods}

    for m in metric_names:
        row = {"Metric": m}
        for name, _, _ in periods:
            row[name] = period_data[name][m]
        perf_rows.append(row)

    df_perf = pd.DataFrame(perf_rows)
    perf_compare = build_compare_values(lambda s, e: meta_metrics(df_meta, s, e), metric_names)
    render_beige_table(df_perf, selected_col_name=selected_label, compare_values=perf_compare)

    st.markdown("### 💷 Revenue")
    st.caption("All Purchase revenue data is coming from Shopify (TOTAL_SALES, coffee ×5/6, refunds excluded). Total Coffee includes complete order value which contains any coffee item.")

    df_meta_pv = session.sql("""
        SELECT
            DATE_START,
            NVL(GET(FILTER(ACTION_VALUES, a -> a:action_type::STRING = 'offsite_conversion.fb_pixel_purchase')[0], 'value')::FLOAT, 0) AS META_PURCHASE_VALUE
        FROM VAHDAM_DB.MAPLEMONK.META_UK_CUSTOMCAMPAIGNS_DATA
        WHERE DATE_START >= '{lower}' AND DATE_START <= '{yesterday}'
          AND CAMPAIGN_NAME NOT ILIKE '%AWAR%'
    """.format(lower=month_minus3_start_q, yesterday=yesterday)).to_pandas()
    df_meta_pv["DATE_START"] = pd.to_datetime(df_meta_pv["DATE_START"]).dt.date

    df_shopify = session.sql("""
        WITH coffee_orders AS (
            SELECT DISTINCT ORDER_ID
            FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUK_ALL_ORDERS_ITEMS
            WHERE ORDER_STATUS != 'CANCELLED' AND IS_REFUND = 0
              AND DATE(ORDER_TIMESTAMP) >= '{lower}' AND DATE(ORDER_TIMESTAMP) <= '{yesterday}'
              AND PRODUCT_NAME ILIKE '%coffee%'
        ),
        first_orders AS (
            SELECT ORDER_ID, ORDER_NAME,
                ROW_NUMBER() OVER (PARTITION BY EMAIL ORDER BY ORDER_TIMESTAMP, ORDER_ID) AS RN
            FROM (
                SELECT DISTINCT ORDER_ID, ORDER_NAME, EMAIL, ORDER_TIMESTAMP
                FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUK_ALL_ORDERS_ITEMS
                WHERE ORDER_STATUS != 'CANCELLED' AND IS_REFUND = 0
            )
        ),
        order_summary AS (
            SELECT
                DATE(ORDER_TIMESTAMP) AS DATE_START,
                ORDER_ID,
                SUM({net_sales_expr}) AS ORDER_VALUE
            FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUK_ALL_ORDERS_ITEMS
            WHERE ORDER_STATUS != 'CANCELLED' AND IS_REFUND = 0
              AND DATE(ORDER_TIMESTAMP) >= '{lower}' AND DATE(ORDER_TIMESTAMP) <= '{yesterday}'
            GROUP BY DATE(ORDER_TIMESTAMP), ORDER_ID
        )
        SELECT
            os.DATE_START,
            SUM(os.ORDER_VALUE) AS ALL_REVENUE,
            SUM(CASE WHEN fo.RN = 1 THEN os.ORDER_VALUE ELSE 0 END) AS NEW_PURCHASE_VALUE,
            SUM(CASE WHEN co.ORDER_ID IS NOT NULL THEN os.ORDER_VALUE ELSE 0 END) AS COFFEE_PURCHASE_VALUE
        FROM order_summary os
        LEFT JOIN first_orders fo ON os.ORDER_ID = fo.ORDER_ID
        LEFT JOIN coffee_orders co ON os.ORDER_ID = co.ORDER_ID
        GROUP BY os.DATE_START
    """.format(lower=month_minus3_start_q, yesterday=yesterday, net_sales_expr=NET_SALES_EXPR)).to_pandas()
    df_shopify["DATE_START"] = pd.to_datetime(df_shopify["DATE_START"]).dt.date

    def sum_col(df, col, start, end):
        mask = (df["DATE_START"] >= start) & (df["DATE_START"] <= end)
        return round(df.loc[mask, col].sum(), 2)

    rev_rows = []
    for period_name, start, end in periods:
        rev_rows.append({
            "period": period_name,
            "Meta Purchase Value": sum_col(df_meta_pv, "META_PURCHASE_VALUE", start, end),
            "All New Purchase Value": sum_col(df_shopify, "NEW_PURCHASE_VALUE", start, end),
            "Total Coffee Purchase Value": sum_col(df_shopify, "COFFEE_PURCHASE_VALUE", start, end),
            "All Revenue": sum_col(df_shopify, "ALL_REVENUE", start, end),
        })

    rev_metrics = ["Meta Purchase Value", "All New Purchase Value", "Total Coffee Purchase Value", "All Revenue"]
    rev_table_rows = []
    for m in rev_metrics:
        row = {"Metric": m}
        for r in rev_rows:
            row[r["period"]] = r[m]
        rev_table_rows.append(row)

    df_rev = pd.DataFrame(rev_table_rows)

    def _rev_values(s, e):
        return {
            "Meta Purchase Value": sum_col(df_meta_pv, "META_PURCHASE_VALUE", s, e),
            "All New Purchase Value": sum_col(df_shopify, "NEW_PURCHASE_VALUE", s, e),
            "Total Coffee Purchase Value": sum_col(df_shopify, "COFFEE_PURCHASE_VALUE", s, e),
            "All Revenue": sum_col(df_shopify, "ALL_REVENUE", s, e),
        }
    rev_compare = build_compare_values(_rev_values, rev_metrics)
    render_beige_table(df_rev, selected_col_name=selected_label, compare_values=rev_compare)

    st.markdown("### 🎯 ROAS · CR · AOV")

    df_shopify_orders = session.sql("""
        WITH first_orders AS (
            SELECT ORDER_ID,
                ROW_NUMBER() OVER (PARTITION BY EMAIL ORDER BY ORDER_TIMESTAMP, ORDER_ID) AS RN
            FROM (
                SELECT DISTINCT ORDER_ID, EMAIL, ORDER_TIMESTAMP
                FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUK_ALL_ORDERS_ITEMS
                WHERE ORDER_STATUS != 'CANCELLED' AND IS_REFUND = 0
            )
        )
        SELECT
            DATE(o.ORDER_TIMESTAMP) AS DATE_START,
            COUNT(DISTINCT o.ORDER_ID) AS TOTAL_ORDERS,
            COUNT(DISTINCT CASE WHEN fo.RN = 1 THEN o.ORDER_ID END) AS NEW_ORDERS,
            COUNT(DISTINCT CASE WHEN
                    o.TAGS IS NULL
                    OR o.TAGS NOT ILIKE '%Billing cycle%'
                    OR (o.TAGS ILIKE '%Billing cycle #1%'
                        AND o.TAGS NOT ILIKE '%Billing cycle #2%' AND o.TAGS NOT ILIKE '%Billing cycle #3%'
                        AND o.TAGS NOT ILIKE '%Billing cycle #4%' AND o.TAGS NOT ILIKE '%Billing cycle #5%'
                        AND o.TAGS NOT ILIKE '%Billing cycle #6%' AND o.TAGS NOT ILIKE '%Billing cycle #7%'
                        AND o.TAGS NOT ILIKE '%Billing cycle #8%' AND o.TAGS NOT ILIKE '%Billing cycle #9%')
                    THEN o.ORDER_ID END) AS NON_SUB_ORDERS,
            SUM({net_sales_expr}) AS TOTAL_SALES
        FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUK_ALL_ORDERS_ITEMS o
        LEFT JOIN first_orders fo ON o.ORDER_ID = fo.ORDER_ID
        WHERE o.ORDER_STATUS != 'CANCELLED' AND o.IS_REFUND = 0
          AND DATE(o.ORDER_TIMESTAMP) >= '{lower}' AND DATE(o.ORDER_TIMESTAMP) <= '{yesterday}'
        GROUP BY DATE(o.ORDER_TIMESTAMP)
    """.format(lower=month_minus3_start_q, yesterday=yesterday, net_sales_expr=NET_SALES_EXPR)).to_pandas()

    df_new_plus_purchase = session.sql("""
        WITH order_tags AS (
            SELECT
                DATE(ORDER_TIMESTAMP) AS DATE_START,
                ORDER_ID,
                SUM({net_sales_expr}) AS ORDER_REVENUE
            FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUK_ALL_ORDERS_ITEMS
            WHERE ORDER_STATUS != 'CANCELLED' AND IS_REFUND = 0
              AND DATE(ORDER_TIMESTAMP) >= '{lower}' AND DATE(ORDER_TIMESTAMP) <= '{yesterday}'
              AND (
                  TAGS IS NULL
                  OR TAGS NOT ILIKE '%Billing cycle%'
                  OR (TAGS ILIKE '%Billing cycle #1%' AND TAGS NOT ILIKE '%Billing cycle #2%'
                      AND TAGS NOT ILIKE '%Billing cycle #3%' AND TAGS NOT ILIKE '%Billing cycle #4%'
                      AND TAGS NOT ILIKE '%Billing cycle #5%' AND TAGS NOT ILIKE '%Billing cycle #6%'
                      AND TAGS NOT ILIKE '%Billing cycle #7%' AND TAGS NOT ILIKE '%Billing cycle #8%'
                      AND TAGS NOT ILIKE '%Billing cycle #9%')
              )
            GROUP BY DATE(ORDER_TIMESTAMP), ORDER_ID
        )
        SELECT DATE_START, SUM(ORDER_REVENUE) AS NEW_PLUS_REVENUE
        FROM order_tags
        GROUP BY DATE_START
    """.format(lower=month_minus3_start_q, yesterday=yesterday, net_sales_expr=NET_SALES_EXPR)).to_pandas()
    df_new_plus_purchase["DATE_START"] = pd.to_datetime(df_new_plus_purchase["DATE_START"]).dt.date
    df_shopify_orders["DATE_START"] = pd.to_datetime(df_shopify_orders["DATE_START"]).dt.date

    df_sub_retention = session.sql("""
        SELECT DATE(ORDER_TIMESTAMP) AS DATE_START,
            SUM({net_sales_expr}) AS SUB_RETENTION_REVENUE
        FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUK_ALL_ORDERS_ITEMS
        WHERE ORDER_STATUS != 'CANCELLED' AND IS_REFUND = 0
          AND TAGS ILIKE '%Billing Cycle%'
          AND TAGS NOT ILIKE '%Billing cycle #1%'
          AND DATE(ORDER_TIMESTAMP) >= '{lower}' AND DATE(ORDER_TIMESTAMP) <= '{yesterday}'
        GROUP BY DATE(ORDER_TIMESTAMP)
    """.format(lower=month_minus3_start_q, yesterday=yesterday, net_sales_expr=NET_SALES_EXPR)).to_pandas()
    df_sub_retention["DATE_START"] = pd.to_datetime(df_sub_retention["DATE_START"]).dt.date

    def roas_metrics(period_name, start, end):
        total_ad_spent = sum_spend(df_raw, start, end)
        new_pv = sum_col(df_shopify, "NEW_PURCHASE_VALUE", start, end)
        meta_pv = sum_col(df_meta_pv, "META_PURCHASE_VALUE", start, end)
        all_revenue = sum_col(df_shopify, "ALL_REVENUE", start, end)
        coffee_pv = sum_col(df_shopify, "COFFEE_PURCHASE_VALUE", start, end)
        sub_ret = sum_col(df_sub_retention, "SUB_RETENTION_REVENUE", start, end)
        new_plus_rev = sum_col(df_new_plus_purchase, "NEW_PLUS_REVENUE", start, end)

        mask = (df_shopify_orders["DATE_START"] >= start) & (df_shopify_orders["DATE_START"] <= end)
        subset = df_shopify_orders.loc[mask]
        total_orders = subset["TOTAL_ORDERS"].sum()
        new_orders = subset["NEW_ORDERS"].sum()
        non_sub_orders = subset["NON_SUB_ORDERS"].sum()
        total_sales = subset["TOTAL_SALES"].sum()

        mask_lpv = (df_meta["DATE_START"] >= start) & (df_meta["DATE_START"] <= end)
        lpv_total = df_meta.loc[mask_lpv, "LANDING_PAGE_VIEWS"].sum()

        new_purchase_roas = round(new_pv / total_ad_spent, 2) if total_ad_spent > 0 else 0
        new_plus_purchase_roas = round(new_plus_rev / total_ad_spent, 2) if total_ad_spent > 0 else 0
        meta_roas = round(meta_pv / total_ad_spent, 2) if total_ad_spent > 0 else 0
        aov = round(total_sales / total_orders, 2) if total_orders > 0 else 0
        new_aov = round(new_pv / new_orders, 2) if new_orders > 0 else 0
        cpa = round(total_ad_spent / new_orders, 2) if new_orders > 0 else 0
        cr = round((non_sub_orders / lpv_total * 100), 2) if lpv_total > 0 else 0
        blended_roas = round(all_revenue / total_ad_spent, 2) if total_ad_spent > 0 else 0
        coffee_blended = round(coffee_pv / total_ad_spent, 2) if total_ad_spent > 0 else 0

        return {
            "New Purchase ROAS": new_purchase_roas,
            "NEW+ Purchase ROAS": new_plus_purchase_roas,
            "Just Meta ROAS": meta_roas,
            "ROAS Wanted": 0.82,
            "AOV": aov,
            "New AOV": new_aov,
            "CPA": cpa,
            "CR": f"{cr}%",
            "Blended ROAS": blended_roas,
            "Coffee Blended": coffee_blended,
            "Sub Retention Revenue": sub_ret,
        }

    roas_metric_names = ["New Purchase ROAS", "NEW+ Purchase ROAS", "Just Meta ROAS", "ROAS Wanted", "AOV", "CPA", "New AOV", "CR", "Blended ROAS", "Coffee Blended", "Sub Retention Revenue"]
    roas_period_data = {name: roas_metrics(name, start, end) for name, start, end in periods}

    roas_table_rows = []
    for m in roas_metric_names:
        row = {"Metric": m}
        for name, _, _ in periods:
            row[name] = roas_period_data[name][m]
        roas_table_rows.append(row)

    df_roas = pd.DataFrame(roas_table_rows)
    roas_compare = build_compare_values(lambda s, e: roas_metrics("", s, e), roas_metric_names)
    render_beige_table(df_roas, selected_col_name=selected_label, compare_values=roas_compare)
    st.markdown("### 📊 P&L (COGS incl. Duty · FX 121.05 INR/GBP · coffee ×5/6 · refunds excluded · Loop 0.7% of sub sales)")

    # ─── P&L daily aggregation — IDENTICAL cost logic to the UK master query ─
    df_pnl_daily = session.sql("""
        WITH mapping AS (
            SELECT TRIM("D2C UK") AS d2c_uk_sku, ANY_VALUE(TRIM("Common SKU ID")) AS common_sku_id
            FROM VAHDAM_DB.MAPLEMONK.VAHDAM_FY27_INPUTS_PRODUCT_MAPPING
            WHERE "D2C UK" IS NOT NULL AND TRIM("D2C UK") != ''
            GROUP BY TRIM("D2C UK")
        ),
        cost_sheet AS (
            SELECT
                TRIM(SKU) AS sku,
                TRY_TO_DECIMAL(REPLACE("COGS (INR)",',',''),30,5)      AS cogs_inr,
                TRY_TO_DECIMAL(REPLACE("Duty (GBP)",',',''),30,5)      AS duty_gbp,
                TRY_TO_DECIMAL(REPLACE("Outbound(GBP)",',',''),30,5)   AS outbound_gbp,
                TRY_TO_DECIMAL(REPLACE("Last Mile / mcf",',',''),30,5) AS lastmile_gbp
            FROM VAHDAM_DB.MAPLEMONK.FY27_INPUTS_D2C_UK_SC_COSTS
            WHERE TRIM(SKU) IS NOT NULL AND TRIM(SKU) != ''
        ),
        cost_via_common_ranked AS (
            SELECT m.common_sku_id, c.cogs_inr, c.duty_gbp, c.outbound_gbp, c.lastmile_gbp,
                ROW_NUMBER() OVER (PARTITION BY m.common_sku_id ORDER BY
                    CASE WHEN LOWER(c.sku) LIKE '%frother%' THEN 1 ELSE 0 END +
                    CASE WHEN LOWER(c.sku) LIKE '%gift%'    THEN 1 ELSE 0 END +
                    CASE WHEN LOWER(c.sku) LIKE '%bundle%'  THEN 1 ELSE 0 END +
                    CASE WHEN LOWER(c.sku) LIKE '%kit%'     THEN 1 ELSE 0 END +
                    CASE WHEN LOWER(c.sku) LIKE '%pack of%' THEN 1 ELSE 0 END,
                    LENGTH(c.sku)) AS rn
            FROM cost_sheet c JOIN mapping m ON m.d2c_uk_sku = c.sku
        ),
        cost_via_common AS (
            SELECT common_sku_id, cogs_inr, duty_gbp, outbound_gbp, lastmile_gbp
            FROM cost_via_common_ranked WHERE rn = 1
        ),
        fy27_cogs AS (
            SELECT TRIM(MATERIAL) AS common_sku_id, AVG(TRY_TO_DECIMAL(REPLACE(COGS,',',''),30,5)) AS cogs_inr
            FROM VAHDAM_DB.MAPLEMONK.VAHDAM_FY27_INPUTS_COGS_SHEET
            WHERE MATERIAL IS NOT NULL AND TRY_TO_DECIMAL(REPLACE(COGS,',',''),30,5) IS NOT NULL
            GROUP BY TRIM(MATERIAL)
        )
        SELECT
            li.ORDER_TIMESTAMP::DATE AS DATE_START,
            ROUND(SUM(
                CASE WHEN li.PRODUCT_NAME ILIKE '%coffee%' THEN li.TOTAL_SALES * 5.0/6.0
                     ELSE li.TOTAL_SALES END
            ), 2) AS NET_SALES_GBP,
            ROUND(SUM(
                CASE WHEN li.TAGS ILIKE '%Billing Cycle%' THEN li.TOTAL_SALES ELSE 0 END
            ), 2) AS SUB_NET_SALES_RAW,
            ROUND(SUM(COALESCE(cs.cogs_inr, cvc.cogs_inr, fc.cogs_inr, 0) * li.QUANTITY / 121.05), 2) AS COGS_GBP,
            ROUND(SUM(COALESCE(cs.duty_gbp,     cvc.duty_gbp,     0) * li.QUANTITY), 2) AS DUTY_GBP,
            ROUND(SUM(COALESCE(cs.outbound_gbp, cvc.outbound_gbp, 0) * li.QUANTITY), 2) AS OUTBOUND_GBP,
            ROUND(SUM(COALESCE(cs.lastmile_gbp, cvc.lastmile_gbp, 0) * li.QUANTITY), 2) AS LASTMILE_GBP
        FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUK_ALL_ORDERS_ITEMS li
        LEFT JOIN cost_sheet cs ON cs.sku = TRIM(li.SKU)
        LEFT JOIN mapping m ON m.d2c_uk_sku = TRIM(li.SKU)
        LEFT JOIN cost_via_common cvc ON cvc.common_sku_id = m.common_sku_id AND cs.cogs_inr IS NULL
        LEFT JOIN fy27_cogs fc ON fc.common_sku_id = m.common_sku_id AND cs.cogs_inr IS NULL AND cvc.cogs_inr IS NULL
        WHERE li.ORDER_TIMESTAMP::DATE >= '{lower}' AND li.ORDER_TIMESTAMP::DATE <= '{yesterday}'
          AND li.ORDER_STATUS != 'CANCELLED' AND li.IS_REFUND = 0
        GROUP BY li.ORDER_TIMESTAMP::DATE
    """.format(lower=month_minus3_start_q, yesterday=yesterday)).to_pandas()
    df_pnl_daily["DATE_START"] = pd.to_datetime(df_pnl_daily["DATE_START"]).dt.date
    for _c in ["NET_SALES_GBP", "SUB_NET_SALES_RAW", "COGS_GBP", "DUTY_GBP", "OUTBOUND_GBP", "LASTMILE_GBP"]:
        df_pnl_daily[_c] = pd.to_numeric(df_pnl_daily[_c], errors="coerce").fillna(0.0)

    # PG commission = actual processor fees (FEE) from balance transactions, by order date
    df_pg_fees = session.sql("""
        SELECT DATE(o.ORDER_TIMESTAMP) AS DATE_START, SUM(bt.FEE) AS PG_FEE
        FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUK_BALANCE_TRANSACTIONS bt
        JOIN (
            SELECT DISTINCT ORDER_ID, ORDER_TIMESTAMP
            FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUK_ALL_ORDERS_ITEMS
            WHERE ORDER_STATUS != 'CANCELLED' AND IS_REFUND = 0
        ) o ON o.ORDER_ID = bt.SOURCE_ORDER_ID
        WHERE bt.TYPE = 'charge'
          AND DATE(o.ORDER_TIMESTAMP) >= '{lower}' AND DATE(o.ORDER_TIMESTAMP) <= '{yesterday}'
        GROUP BY DATE(o.ORDER_TIMESTAMP)
    """.format(lower=month_minus3_start_q, yesterday=yesterday)).to_pandas()
    df_pg_fees["DATE_START"] = pd.to_datetime(df_pg_fees["DATE_START"]).dt.date
    df_pg_fees["PG_FEE"] = pd.to_numeric(df_pg_fees["PG_FEE"], errors="coerce").fillna(0.0)

    # Refunds (line-item SUBTOTAL + transaction-only AMOUNT), by refund date (PROCESSED_AT)
    df_refunds = session.sql("""
        WITH refunds AS (
            SELECT * FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUK_ORDERS_REFUNDS
            QUALIFY ROW_NUMBER() OVER (PARTITION BY ID ORDER BY _AIRBYTE_EMITTED_AT DESC) = 1
        ),
        rli_deduped AS (
            SELECT * FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUK_ORDERS_REFUNDS_REFUND_LINE_ITEMS
            QUALIFY ROW_NUMBER() OVER (PARTITION BY ID ORDER BY _AIRBYTE_EMITTED_AT DESC) = 1
        ),
        txn_deduped AS (
            SELECT * FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUK_ORDERS_REFUNDS_TRANSACTIONS
            QUALIFY ROW_NUMBER() OVER (PARTITION BY ID ORDER BY _AIRBYTE_EMITTED_AT DESC) = 1
        ),
        line_item_refunds AS (
            SELECT r.PROCESSED_AT::DATE AS REFUND_DATE, TRY_TO_DOUBLE(rli.SUBTOTAL) AS REFUND_AMT
            FROM refunds r
            JOIN rli_deduped rli ON r._AIRBYTE_REFUNDS_HASHID = rli._AIRBYTE_REFUNDS_HASHID
        ),
        txn_only_refunds AS (
            SELECT r.PROCESSED_AT::DATE AS REFUND_DATE, TRY_TO_DOUBLE(txn.AMOUNT) AS REFUND_AMT
            FROM refunds r
            JOIN txn_deduped txn ON r._AIRBYTE_REFUNDS_HASHID = txn._AIRBYTE_REFUNDS_HASHID
            WHERE NOT EXISTS (
                SELECT 1 FROM rli_deduped rli WHERE rli._AIRBYTE_REFUNDS_HASHID = r._AIRBYTE_REFUNDS_HASHID
            )
        )
        SELECT REFUND_DATE AS DATE_START, SUM(REFUND_AMT) AS REFUND_AMT
        FROM (
            SELECT REFUND_DATE, REFUND_AMT FROM line_item_refunds
            UNION ALL
            SELECT REFUND_DATE, REFUND_AMT FROM txn_only_refunds
        )
        WHERE REFUND_DATE >= '{lower}' AND REFUND_DATE <= '{yesterday}'
        GROUP BY REFUND_DATE
    """.format(lower=month_minus3_start_q, yesterday=yesterday)).to_pandas()
    df_refunds["DATE_START"] = pd.to_datetime(df_refunds["DATE_START"]).dt.date
    df_refunds["REFUND_AMT"] = pd.to_numeric(df_refunds["REFUND_AMT"], errors="coerce").fillna(0.0)

    def software_platform_cost_gbp(start, end):
        """Day-wise prorated tech cost (GBP) over [start, end]. Each calendar
        month's fixed cost ($ base, +10%/mo, USD->INR->GBP) is spread evenly
        across its days, so a full month = full monthly cost, MTD/Last-7 = the
        matching fraction."""
        total = 0.0
        cur = start
        while cur <= end:
            months = (cur.year - SOFTWARE_ANCHOR_YEAR) * 12 + (cur.month - SOFTWARE_ANCHOR_MONTH)
            monthly_gbp = SOFTWARE_BASE_COST_USD * ((1 + SOFTWARE_MOM_GROWTH) ** months) * USD_TO_INR / FX_RATE
            total += monthly_gbp / calendar.monthrange(cur.year, cur.month)[1]
            cur += timedelta(days=1)
        return round(total, 2)

    def pnl_metrics(start, end):
        mask = (df_pnl_daily["DATE_START"] >= start) & (df_pnl_daily["DATE_START"] <= end)
        subset = df_pnl_daily.loc[mask]

        net_sales = round(subset["NET_SALES_GBP"].sum(), 2)

        cogs_goods = round(subset["COGS_GBP"].sum(), 2)
        duty       = round(subset["DUTY_GBP"].sum(), 2)
        cogs       = round(cogs_goods + duty, 2)
        cogs_pct   = round((cogs / net_sales * 100), 2) if net_sales > 0 else 0
        gross_margin = round(net_sales - cogs, 2)
        outbound  = round(subset["OUTBOUND_GBP"].sum(), 2)
        last_mile = round(subset["LASTMILE_GBP"].sum(), 2)

        mask_pg = (df_pg_fees["DATE_START"] >= start) & (df_pg_fees["DATE_START"] <= end)
        pg_commission = round(df_pg_fees.loc[mask_pg, "PG_FEE"].sum(), 2)
        pg_pct = round((pg_commission / net_sales * 100), 2) if net_sales > 0 else 0

        shopify_costs = 0
        storage = 0

        # Loop commission = 0.7% of subscription net sales (raw) — now a CM1 cost
        sub_net_sales_raw = round(subset["SUB_NET_SALES_RAW"].sum(), 2)
        loop_commission = round(sub_net_sales_raw * LOOP_COMMISSION_RATE, 2)

        cm1 = round(net_sales - cogs - pg_commission - outbound - last_mile - storage - loop_commission, 2)
        cm1_pct = round((cm1 / net_sales * 100), 2) if net_sales > 0 else 0

        total_ad_spent = sum_spend(df_raw, start, end)
        agency_fees = 1
        software_gross_gbp = software_platform_cost_gbp(start, end)   # day-wise prorated
        tech_cost = round(software_gross_gbp - loop_commission, 2)    # Loop still carved out of tech
        cm2 = round(cm1 - total_ad_spent - agency_fees - tech_cost, 2)  # Loop NOT re-subtracted (it's in CM1)

        supply_pct = round(((cogs + outbound + last_mile + storage) / net_sales * 100), 2) if net_sales > 0 else 0

        return {
            "Net Sales (After Tax)": net_sales,
            "COGS (incl. Duty)": cogs,
            "COGS %": f"{cogs_pct}%",
            "Gross Margin": gross_margin,
            "Outbound": outbound,
            "PG Commission": pg_commission,
            "PG Commission %": f"{pg_pct}%",
            "Shopify Costs": shopify_costs,
            "Last Mile (per-SKU)": last_mile,
            "Storage": storage,
            "Supply %": f"{supply_pct}%",
            "Loop Commission": loop_commission,
            "CM1": cm1,
            "CM1 %": f"{cm1_pct}%",
            "Performance Marketing Cost": total_ad_spent,
            "Agency Fees": agency_fees,
            "Software & Platform Cost": tech_cost,
            "CM2": cm2,
            "_COGS_goods": cogs_goods,
            "_Duty": duty,
            "_Subscription Net Sales (raw)": sub_net_sales_raw,
            "_Software (gross GBP)": software_gross_gbp,
        }

    pnl_metric_names = ["Net Sales (After Tax)", "COGS (incl. Duty)", "COGS %",
                        "Gross Margin", "Outbound", "PG Commission", "PG Commission %",
                        "Shopify Costs", "Last Mile (per-SKU)", "Storage", "Supply %",
                        "Loop Commission", "CM1", "CM1 %",
                        "Performance Marketing Cost", "Agency Fees",
                        "Software & Platform Cost", "CM2"]

    pnl_period_data = {name: pnl_metrics(start, end) for name, start, end in periods}

    pnl_table_rows = []
    for m in pnl_metric_names:
        row = {"Metric": m}
        for name, _, _ in periods:
            row[name] = pnl_period_data[name][m]
        pnl_table_rows.append(row)

    df_pnl = pd.DataFrame(pnl_table_rows)
    pnl_compare = build_compare_values(lambda s, e: pnl_metrics(s, e), pnl_metric_names)
    render_beige_table(df_pnl, selected_col_name=selected_label, compare_values=pnl_compare)

    st.caption(
        "**Loop Commission** = 0.7% × subscription net sales (orders tagged 'Billing Cycle', raw TOTAL_SALES, no coffee ×5/6). "
        "**Software & Platform Cost** = fixed monthly software ($5058 base for May, +10%/mo, converted "
        "$→INR @90.53 →GBP @121.05) **minus** the Loop Commission. CM2 deducts ad spend, agency, Loop and the net tech cost."
    )

    # ─── Collapsible COGS breakdown: goods vs duty ────────────────────
    with st.expander("🔍 COGS breakdown — goods vs duty (the COGS row above = goods + duty)"):
        _bd_names = ["COGS (goods only)", "Duty", "COGS (incl. Duty)"]
        _bd_src   = {"COGS (goods only)": "_COGS_goods", "Duty": "_Duty", "COGS (incl. Duty)": "COGS (incl. Duty)"}

        _bd_rows = []
        for _disp in _bd_names:
            _row = {"Metric": _disp}
            for _name, _, _ in periods:
                _row[_name] = pnl_period_data[_name][_bd_src[_disp]]
            _bd_rows.append(_row)
        df_cogs_bd = pd.DataFrame(_bd_rows)

        def _cogs_bd_values(s, e):
            _d = pnl_metrics(s, e)
            return {k: _d[_bd_src[k]] for k in _bd_names}
        _cogs_bd_compare = build_compare_values(_cogs_bd_values, _bd_names)

        render_beige_table(df_cogs_bd, selected_col_name=selected_label, compare_values=_cogs_bd_compare)
        st.caption("Goods = COGS_INR ÷ 121.05 × qty. Duty = Duty(GBP) × qty. Both pulled per-SKU from the FY27 D2C-UK cost sheet, matching the master query.")

    # ─── Collapsible Software / Loop reconciliation ──────────────────
    with st.expander("🔍 Tech cost build-up — software (gross) − Loop Commission"):
        _tc_names = ["Software (gross GBP)", "Loop Commission", "Software & Platform Cost", "Subscription Net Sales (raw)"]
        _tc_src   = {
            "Software (gross GBP)": "_Software (gross GBP)",
            "Loop Commission": "Loop Commission",
            "Software & Platform Cost": "Software & Platform Cost",
            "Subscription Net Sales (raw)": "_Subscription Net Sales (raw)",
        }
        _tc_rows = []
        for _disp in _tc_names:
            _row = {"Metric": _disp}
            for _name, _, _ in periods:
                _row[_name] = pnl_period_data[_name][_tc_src[_disp]]
            _tc_rows.append(_row)
        df_tc = pd.DataFrame(_tc_rows)

        def _tc_values(s, e):
            _d = pnl_metrics(s, e)
            return {k: _d[_tc_src[k]] for k in _tc_names}
        _tc_compare = build_compare_values(_tc_values, _tc_names)

        render_beige_table(df_tc, selected_col_name=selected_label, compare_values=_tc_compare)
        st.caption("Software (gross): May $5058 ≈ £3,783 · Jun ≈ £4,161 · Apr ≈ £3,439. Reported tech cost = gross − Loop Commission.")

    # ─────────────────────────────────────────────────────────────────
    # COHORT LTV + SUBSCRIPTION RETENTION
    # ─────────────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("## Cohort LTV & Subscription Retention")

    _c1, _c2 = st.columns(2)
    with _c1:
        cohort_from = st.date_input(
            "Cohort window — From",
            value=yesterday - timedelta(days=29),
            key="d2c_uk_cohort_from",
        )
    with _c2:
        cohort_to = st.date_input(
            "Cohort window — To",
            value=yesterday,
            key="d2c_uk_cohort_to",
        )

    if cohort_from > cohort_to:
        st.error("'From' date must be on or before 'To'.")
        st.stop()

    # ─────────────────────────────────────────────────────────────────
    # SECTION 1 — COHORT LTV
    # ─────────────────────────────────────────────────────────────────
    st.markdown("### Cohort LTV — customers acquired in picker window")
    st.caption(
        "Customer = unique email (lowercased). "
        "Net revenue = TOTAL_SALES (coffee ×5/6), refunds excluded. "
        "Subscription renewals naturally compound into LTV."
    )

    df_cohort_raw = session.sql(f"""
        WITH cohort_customers AS (
            SELECT
                LOWER(TRIM(EMAIL))           AS EMAIL,
                MIN(DATE(ORDER_TIMESTAMP))   AS FIRST_ORDER_DATE
            FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUK_ALL_ORDERS_ITEMS
            WHERE ORDER_STATUS != 'CANCELLED' AND IS_REFUND = 0
              AND EMAIL IS NOT NULL
              AND TRIM(EMAIL) != ''
            GROUP BY LOWER(TRIM(EMAIL))
            HAVING MIN(DATE(ORDER_TIMESTAMP)) >= '{cohort_from}'
               AND MIN(DATE(ORDER_TIMESTAMP)) <= '{cohort_to}'
        )
        SELECT
            FLOOR(DATEDIFF('day', c.FIRST_ORDER_DATE, DATE(o.ORDER_TIMESTAMP)) / 30) AS MONTH_NUM,
            COUNT(DISTINCT c.EMAIL)                   AS ACTIVE_CUSTOMERS,
            COUNT(DISTINCT o.ORDER_ID)                AS ORDERS,
            ROUND(SUM(CASE WHEN o.PRODUCT_NAME ILIKE '%coffee%' THEN o.TOTAL_SALES * 5.0/6.0
                           ELSE o.TOTAL_SALES END), 2) AS REVENUE
        FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUK_ALL_ORDERS_ITEMS o
        JOIN cohort_customers c ON LOWER(TRIM(o.EMAIL)) = c.EMAIL
        WHERE o.ORDER_STATUS != 'CANCELLED' AND o.IS_REFUND = 0
        GROUP BY MONTH_NUM
        ORDER BY MONTH_NUM
    """).to_pandas()

    if df_cohort_raw.empty:
        st.info("No customers acquired in the selected window.")
    else:
        cohort_size        = int(df_cohort_raw.loc[df_cohort_raw["MONTH_NUM"] == 0, "ACTIVE_CUSTOMERS"].sum())
        cumulative_revenue = round(float(df_cohort_raw["REVENUE"].sum()), 2)
        ltv_per_customer   = round(cumulative_revenue / cohort_size, 2) if cohort_size else 0.0

        _k1, _k2, _k3 = st.columns(3)
        _k1.metric("Cohort size",        f"{cohort_size:,} unique customers (by email)")
        _k2.metric("Cumulative revenue", f"£{cumulative_revenue:,.2f}")
        _k3.metric("LTV per customer",   f"£{ltv_per_customer:.2f}")

        _cum_rev  = 0.0
        _ltv_rows = []
        for _, _r in df_cohort_raw.iterrows():
            _m     = int(_r["MONTH_NUM"])
            _rev   = round(float(_r["REVENUE"]), 2)
            _cum_rev += _rev
            _act   = int(_r["ACTIVE_CUSTOMERS"])
            _ret   = round(_act / cohort_size * 100, 2) if cohort_size else 0.0
            _cltv  = round(_cum_rev / cohort_size, 2) if cohort_size else 0.0
            _label = (pd.Timestamp(cohort_from) + relativedelta(months=_m)).strftime("%b %Y")
            _ltv_rows.append({
                "Month since acquisition": f"M{_m} · {_label}",
                "Active customers":        _act,
                "Retention":               f"{_ret:.2f}%",
                "Orders":                  int(_r["ORDERS"]),
                "Revenue this month":      f"£{_rev:,.2f}",
                "Cumulative revenue":      f"£{_cum_rev:,.2f}",
                "Cumulative LTV":          f"£{_cltv:.2f}",
            })
        st.dataframe(pd.DataFrame(_ltv_rows), use_container_width=True, hide_index=True)
    st.markdown(
        "<small>"
        "<b>Customer</b> = unique email (lowercased). &nbsp;"
        "<b>Net revenue</b> = TOTAL_SALES (coffee items ×5/6), refunds excluded. &nbsp;"
        "<b>Subscription renewals</b> naturally compound into LTV (they are regular Shopify orders). &nbsp;"
        "Move the picker above to recompute the cohort."
        "</small>",
        unsafe_allow_html=True,
    )
