# -*- coding: utf-8 -*-
"""Shared logic for the USA dashboard tabs (Coffee / Tea / Supplements).
Tabs differ ONLY by ad-campaign filter and category SKU set — everything else
(beige tables, equal-prior-period comparison, PG 2.5%, Loop 0.7%, USD tech cost)
is identical and lives here."""

import streamlit as st
import pandas as pd
from datetime import timedelta
from dateutil.relativedelta import relativedelta
import calendar

# ─── RATES / FIXED COSTS ─────────────────────────────────────────────────────
PG_COMMISSION_RATE     = 0.025     # PG commission = 2.5% of net sales
LOOP_COMMISSION_RATE   = 0.007     # Loop = 0.7% of subscription net sales (raw, no coffee adj)
SOFTWARE_BASE_COST_USD = 4064.0    # tech/software, USD (NO GBP conversion)
SOFTWARE_ANCHOR_YEAR   = 2026
SOFTWARE_ANCHOR_MONTH  = 5         # May 2026 = base
SOFTWARE_MOM_GROWTH    = 0.10      # +10% per calendar month

_SUPP_CAMPAIGNS = (
    "'Conversion_Scale_Ashwagandha_NewB',"
    "'Conversion_BCAP_Turmeric_Curcumin_NewB',"
    "'SUPP_BCAP_Conversion',"
    "'Conversion_Scale_Triphala_NewB',"
    "'Conversion_Scale_Psyllium_NewB',"
    "'Conversion_Scale_Moringa_NewB',"
    "'Conversion_Scale_Turmeric_NewB'"
)
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

def _config(tab):
    cfg = {
        "COFFEE": {
            "category": "Coffee",
            "meta_filter":   "AND CAMPAIGN_NAME ILIKE '%coffee%'",
            "google_filter": "AND \"campaign.name\" ILIKE '%coffee%'",
        },
        "SUPPLEMENTS": {
            "category": "Supplements",
            "meta_filter":   "AND CAMPAIGN_NAME IN ({s})".format(s=_SUPP_CAMPAIGNS),
            "google_filter": "AND \"campaign.name\" IN ({s})".format(s=_SUPP_CAMPAIGNS),
        },
        "TEA": {
            "category": "Tea and Botanicals",
            "meta_filter":   "AND CAMPAIGN_NAME NOT ILIKE '%coffee%' AND CAMPAIGN_NAME NOT IN ({s})".format(s=_SUPP_CAMPAIGNS),
            "google_filter": "AND \"campaign.name\" NOT ILIKE '%coffee%' AND \"campaign.name\" NOT IN ({s})".format(s=_SUPP_CAMPAIGNS),
        },
    }
    return cfg[tab]

def software_platform_cost_usd(start, end):
    """Day-wise prorated tech cost (USD) over [start, end]. Each calendar month's
    fixed cost ($4064 base, +10%/mo) is spread evenly across its days."""
    total = 0.0
    cur = start
    while cur <= end:
        months = (cur.year - SOFTWARE_ANCHOR_YEAR) * 12 + (cur.month - SOFTWARE_ANCHOR_MONTH)
        monthly = SOFTWARE_BASE_COST_USD * ((1 + SOFTWARE_MOM_GROWTH) ** months)
        total += monthly / calendar.monthrange(cur.year, cur.month)[1]
        cur += timedelta(days=1)
    return round(total, 2)

# ─── BEIGE TABLE + %-CHANGE DELTAS (CSS lives in streamlit_app.py) ───────────
def _to_num(v):
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.replace("$", "").replace("£", "").replace(",", "").replace("%", "").strip()
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
    cols = list(df.columns)
    period_cols = [c for c in cols if c != "Metric"]
    html = ["<table class='beige-table'><thead><tr>", "<th>Metric</th>"]
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
            # delta = _delta_html(val, prev_val) if prev_val is not None else ""
            delta = _delta_html(val, prev_val, METRIC_DIRECTION.get(metric, "neutral")) if prev_val is not None else ""
            cls = "selected-col" if c == selected_col_name else ""
            html.append(f"<td class='{cls}'>{val}{delta}</td>")
        html.append("</tr>")
    html.append("</tbody></table>")
    st.markdown("".join(html), unsafe_allow_html=True)


def render_tab(session, tab):
    cfg = _config(tab)
    category      = cfg["category"]
    meta_filter   = cfg["meta_filter"]
    google_filter = cfg["google_filter"]

    from datetime import datetime
    yesterday = (datetime.today() - timedelta(days=1)).date()
    seven_days_ago = yesterday - timedelta(days=6)
    current_month_start = yesterday.replace(day=1)
    prev_month_end = current_month_start - timedelta(days=1)
    prev_month_start = prev_month_end.replace(day=1)
    month_minus2_end = prev_month_start - timedelta(days=1)
    month_minus2_start = month_minus2_end.replace(day=1)
    month_minus3_end = month_minus2_start - timedelta(days=1)
    month_minus3_start = month_minus3_end.replace(day=1)

    periods = [
        ("Last 7 Days", seven_days_ago, yesterday),
        ("Month TD", current_month_start, yesterday),
        (prev_month_start.strftime("%b %Y"), prev_month_start, prev_month_end),
        (month_minus2_start.strftime("%b %Y"), month_minus2_start, month_minus2_end),
        (month_minus3_start.strftime("%b %Y"), month_minus3_start, month_minus3_end),
    ]

    # ─── Comparison windows: each column vs the immediately-preceding like period
    _sel_cmp_to   = seven_days_ago - timedelta(days=1)
    _sel_cmp_from = _sel_cmp_to - timedelta(days=6)
    _mtd_days     = (yesterday - current_month_start).days + 1
    _mtd_cmp_from = prev_month_start
    _mtd_cmp_to   = min(prev_month_start + timedelta(days=_mtd_days - 1), prev_month_end)
    compare_periods = {
        "Last 7 Days":                        (_sel_cmp_from, _sel_cmp_to),
        "Month TD":                           (_mtd_cmp_from, _mtd_cmp_to),
        prev_month_start.strftime("%b %Y"):   (month_minus2_start, month_minus2_end),
        month_minus2_start.strftime("%b %Y"): (month_minus3_start, month_minus3_end),
        month_minus3_start.strftime("%b %Y"): None,
    }

    def build_compare_values(value_fn, names):
        cv = {}
        for col, win in compare_periods.items():
            if win is None:
                continue
            d = value_fn(win[0], win[1])
            cv[col] = {m: d[m] for m in names}
        return cv

    SEL = "Last 7 Days"  # highlighted column

    # ─── AD SPEND ────────────────────────────────────────────────────────────
    df_raw = session.sql("""
        SELECT DATE_START, SPEND
        FROM (
            SELECT DATE_START, SPEND
            FROM VAHDAM_DB.MAPLEMONK.META_USA_CUSTOMCAMPAIGNS_DATA
            WHERE DATE_START >= '{month_minus3_start}' AND DATE_START <= '{yesterday}'
              {meta_filter}
            UNION ALL
            SELECT "segments.date" AS DATE_START, "metrics.cost_micros" / 1000000.0 AS SPEND
            FROM VAHDAM_DB.MAPLEMONK.GOOGLE_ADS_US_CAMPAIGN_DATA
            WHERE "segments.date" >= '{month_minus3_start}' AND "segments.date" <= '{yesterday}'
              {google_filter}
        )
    """.format(month_minus3_start=month_minus3_start, yesterday=yesterday,
               meta_filter=meta_filter, google_filter=google_filter)).to_pandas()
    df_raw["DATE_START"] = pd.to_datetime(df_raw["DATE_START"]).dt.date

    def sum_spend(df, start, end):
        mask = (df["DATE_START"] >= start) & (df["DATE_START"] <= end)
        return round(df.loc[mask, "SPEND"].sum(), 2)

    metrics_data = {"Metric": ["Total Ad Spent"]}
    for name, s, e in periods:
        metrics_data[name] = [sum_spend(df_raw, s, e)]
    df_metrics = pd.DataFrame(metrics_data)

    st.subheader(f"💰 Metrics Summary — {tab}")
    metrics_compare = build_compare_values(
        lambda s, e: {"Total Ad Spent": sum_spend(df_raw, s, e)}, ["Total Ad Spent"])
    render_beige_table(df_metrics, selected_col_name=SEL, compare_values=metrics_compare)

    # ─── PERFORMANCE (Meta, AWAR excluded) ───────────────────────────────────
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
        FROM VAHDAM_DB.MAPLEMONK.META_USA_CUSTOMCAMPAIGNS_DATA
        WHERE DATE_START >= '{month_minus3_start}' AND DATE_START <= '{yesterday}'
          AND CAMPAIGN_NAME NOT ILIKE '%AWAR%'
          {meta_filter}
    """.format(month_minus3_start=month_minus3_start, yesterday=yesterday, meta_filter=meta_filter)).to_pandas()
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
        return {
            "Impressions": round(impressions),
            "Clicks": round(clicks),
            "Landing Page": round(lpv),
            "LPV %": f"{(lpv / clicks * 100) if clicks > 0 else 0:.2f}%",
            "Checkouts": round(checkouts),
            "Average CPM": round((spend / impressions * 1000) if impressions > 0 else 0, 2),
            "Average CPC": round((spend / clicks) if clicks > 0 else 0, 2),
            "CTR": f"{(clicks / impressions * 100) if impressions > 0 else 0:.2f}%",
            "Cost Per Checkout": round((spend / checkouts) if checkouts > 0 else 0, 2),
            "Purchases": round(purchases),
            # "CPA": round((spend / purchases) if purchases > 0 else 0, 2),
        }

    metric_names = ["Impressions", "Clicks", "Landing Page", "LPV %", "Checkouts",
                    "Average CPM", "Average CPC", "CTR", "Cost Per Checkout", "Purchases"] #, "CPA"
    period_data = {name: meta_metrics(df_meta, s, e) for name, s, e in periods}
    perf_rows = []
    for m in metric_names:
        row = {"Metric": m}
        for name, _, _ in periods:
            row[name] = period_data[name][m]
        perf_rows.append(row)
    df_perf = pd.DataFrame(perf_rows)
    perf_compare = build_compare_values(lambda s, e: meta_metrics(df_meta, s, e), metric_names)
    render_beige_table(df_perf, selected_col_name=SEL, compare_values=perf_compare)

    # ─── REVENUE ─────────────────────────────────────────────────────────────
    st.markdown("### 💵 Revenue")
    st.caption(f"All Purchase revenue from Shopify ({category} category). Total Category = complete value of orders containing a {category} item.")

    df_meta_pv = session.sql("""
        SELECT
            DATE_START,
            NVL(GET(FILTER(ACTION_VALUES, a -> a:action_type::STRING = 'offsite_conversion.fb_pixel_purchase')[0], 'value')::FLOAT, 0) AS META_PURCHASE_VALUE
        FROM VAHDAM_DB.MAPLEMONK.META_USA_CUSTOMCAMPAIGNS_DATA
        WHERE DATE_START >= '{month_minus3_start}' AND DATE_START <= '{yesterday}'
          AND CAMPAIGN_NAME NOT ILIKE '%AWAR%'
          {meta_filter}
    """.format(month_minus3_start=month_minus3_start, yesterday=yesterday, meta_filter=meta_filter)).to_pandas()
    df_meta_pv["DATE_START"] = pd.to_datetime(df_meta_pv["DATE_START"]).dt.date

    df_shopify = session.sql("""
        WITH category_skus AS (
            SELECT "D2C US" AS SKU
            FROM VAHDAM_DB.MAPLEMONK.VAHDAM_FY27_INPUTS_PRODUCT_MAPPING
            WHERE "CATEGORY" = '{category}' AND "D2C US" IS NOT NULL AND "D2C US" != ''
        ),
        category_orders AS (
            SELECT DISTINCT o.ORDER_ID
            FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUSA_ALL_ORDERS_ITEMS o
            JOIN category_skus cs ON o.SKU = cs.SKU
            WHERE o.ORDER_STATUS != 'CANCELLED'
              AND DATE(o.ORDER_TIMESTAMP) >= '{month_minus3_start}' AND DATE(o.ORDER_TIMESTAMP) <= '{yesterday}'
        ),
        first_orders AS (
            SELECT ORDER_ID,
                ROW_NUMBER() OVER (PARTITION BY EMAIL ORDER BY ORDER_TIMESTAMP, ORDER_ID) AS RN
            FROM (
                SELECT DISTINCT ORDER_ID, EMAIL, ORDER_TIMESTAMP
                FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUSA_ALL_ORDERS_ITEMS
                WHERE ORDER_STATUS != 'CANCELLED'
            )
        ),
        order_summary AS (
            SELECT
                DATE(o.ORDER_TIMESTAMP) AS DATE_START,
                o.ORDER_ID,
                SUM(o.NET_SALES_BEFORE_TAX) AS ORDER_VALUE
            FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUSA_ALL_ORDERS_ITEMS o
            JOIN category_orders co ON o.ORDER_ID = co.ORDER_ID
            WHERE o.ORDER_STATUS != 'CANCELLED'
              AND DATE(o.ORDER_TIMESTAMP) >= '{month_minus3_start}' AND DATE(o.ORDER_TIMESTAMP) <= '{yesterday}'
            GROUP BY DATE(o.ORDER_TIMESTAMP), o.ORDER_ID
        )
        SELECT
            os.DATE_START,
            SUM(os.ORDER_VALUE) AS ALL_REVENUE,
            SUM(CASE WHEN fo.RN = 1 THEN os.ORDER_VALUE ELSE 0 END) AS NEW_PURCHASE_VALUE,
            SUM(os.ORDER_VALUE) AS COFFEE_PURCHASE_VALUE
        FROM order_summary os
        LEFT JOIN first_orders fo ON os.ORDER_ID = fo.ORDER_ID
        GROUP BY os.DATE_START
    """.format(category=category, month_minus3_start=month_minus3_start, yesterday=yesterday)).to_pandas()
    df_shopify["DATE_START"] = pd.to_datetime(df_shopify["DATE_START"]).dt.date

    def sum_col(df, col, start, end):
        mask = (df["DATE_START"] >= start) & (df["DATE_START"] <= end)
        return round(df.loc[mask, col].sum(), 2)

    def _rev_values(s, e):
        return {
            "Meta Purchase Value": sum_col(df_meta_pv, "META_PURCHASE_VALUE", s, e),
            "All New Purchase Value": sum_col(df_shopify, "NEW_PURCHASE_VALUE", s, e),
            "Total Category Purchase Value": sum_col(df_shopify, "COFFEE_PURCHASE_VALUE", s, e),
            "All Revenue": sum_col(df_shopify, "ALL_REVENUE", s, e),
        }
    rev_metrics = ["Meta Purchase Value", "All New Purchase Value", "Total Category Purchase Value", "All Revenue"]
    rev_table_rows = []
    for m in rev_metrics:
        row = {"Metric": m}
        for name, s, e in periods:
            row[name] = _rev_values(s, e)[m]
        rev_table_rows.append(row)
    df_rev = pd.DataFrame(rev_table_rows)
    rev_compare = build_compare_values(_rev_values, rev_metrics)
    render_beige_table(df_rev, selected_col_name=SEL, compare_values=rev_compare)

    # ─── ROAS · CR · AOV ─────────────────────────────────────────────────────
    st.markdown("### 🎯 ROAS · CR · AOV")

    df_shopify_orders = session.sql("""
        WITH category_skus AS (
            SELECT "D2C US" AS SKU
            FROM VAHDAM_DB.MAPLEMONK.VAHDAM_FY27_INPUTS_PRODUCT_MAPPING
            WHERE "CATEGORY" = '{category}' AND "D2C US" IS NOT NULL AND "D2C US" != ''
        ),
        category_orders AS (
            SELECT DISTINCT o.ORDER_ID
            FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUSA_ALL_ORDERS_ITEMS o
            JOIN category_skus cs ON o.SKU = cs.SKU
            WHERE o.ORDER_STATUS != 'CANCELLED'
              AND DATE(o.ORDER_TIMESTAMP) >= '{month_minus3_start}' AND DATE(o.ORDER_TIMESTAMP) <= '{yesterday}'
        ),
        first_orders AS (
            SELECT ORDER_ID,
                ROW_NUMBER() OVER (PARTITION BY EMAIL ORDER BY ORDER_TIMESTAMP, ORDER_ID) AS RN
            FROM (
                SELECT DISTINCT ORDER_ID, EMAIL, ORDER_TIMESTAMP
                FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUSA_ALL_ORDERS_ITEMS
                WHERE ORDER_STATUS != 'CANCELLED'
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
            SUM(o.NET_SALES_BEFORE_TAX) AS TOTAL_SALES
        FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUSA_ALL_ORDERS_ITEMS o
        JOIN category_orders co ON o.ORDER_ID = co.ORDER_ID
        LEFT JOIN first_orders fo ON o.ORDER_ID = fo.ORDER_ID
        WHERE o.ORDER_STATUS != 'CANCELLED'
          AND DATE(o.ORDER_TIMESTAMP) >= '{month_minus3_start}' AND DATE(o.ORDER_TIMESTAMP) <= '{yesterday}'
        GROUP BY DATE(o.ORDER_TIMESTAMP)
    """.format(category=category, month_minus3_start=month_minus3_start, yesterday=yesterday)).to_pandas()
    df_shopify_orders["DATE_START"] = pd.to_datetime(df_shopify_orders["DATE_START"]).dt.date

    df_sub_retention = session.sql("""
        WITH category_skus AS (
            SELECT "D2C US" AS SKU
            FROM VAHDAM_DB.MAPLEMONK.VAHDAM_FY27_INPUTS_PRODUCT_MAPPING
            WHERE "CATEGORY" = '{category}' AND "D2C US" IS NOT NULL AND "D2C US" != ''
        ),
        category_orders AS (
            SELECT DISTINCT o.ORDER_ID
            FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUSA_ALL_ORDERS_ITEMS o
            JOIN category_skus cs ON o.SKU = cs.SKU
            WHERE o.ORDER_STATUS != 'CANCELLED'
        )
        SELECT DATE(o.ORDER_TIMESTAMP) AS DATE_START,
            SUM(o.NET_SALES_BEFORE_TAX) AS SUB_RETENTION_REVENUE
        FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUSA_ALL_ORDERS_ITEMS o
        JOIN category_orders co ON o.ORDER_ID = co.ORDER_ID
        WHERE o.ORDER_STATUS != 'CANCELLED'
          AND o.TAGS ILIKE '%Billing Cycle%'
          AND o.TAGS NOT ILIKE '%Billing cycle #1%'
          AND DATE(o.ORDER_TIMESTAMP) >= '{month_minus3_start}' AND DATE(o.ORDER_TIMESTAMP) <= '{yesterday}'
        GROUP BY DATE(o.ORDER_TIMESTAMP)
    """.format(category=category, month_minus3_start=month_minus3_start, yesterday=yesterday)).to_pandas()
    df_sub_retention["DATE_START"] = pd.to_datetime(df_sub_retention["DATE_START"]).dt.date

    df_new_plus_purchase = session.sql("""
        WITH category_skus AS (
            SELECT "D2C US" AS SKU
            FROM VAHDAM_DB.MAPLEMONK.VAHDAM_FY27_INPUTS_PRODUCT_MAPPING
            WHERE "CATEGORY" = '{category}' AND "D2C US" IS NOT NULL AND "D2C US" != ''
        ),
        category_orders AS (
            SELECT DISTINCT o.ORDER_ID
            FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUSA_ALL_ORDERS_ITEMS o
            JOIN category_skus cs ON o.SKU = cs.SKU
            WHERE o.ORDER_STATUS != 'CANCELLED'
              AND DATE(o.ORDER_TIMESTAMP) >= '{month_minus3_start}' AND DATE(o.ORDER_TIMESTAMP) <= '{yesterday}'
        ),
        order_tags AS (
            SELECT
                DATE(o.ORDER_TIMESTAMP) AS DATE_START,
                o.ORDER_ID,
                SUM(o.NET_SALES_BEFORE_TAX) AS ORDER_REVENUE
            FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUSA_ALL_ORDERS_ITEMS o
            JOIN category_orders co ON o.ORDER_ID = co.ORDER_ID
            WHERE o.ORDER_STATUS != 'CANCELLED'
              AND DATE(o.ORDER_TIMESTAMP) >= '{month_minus3_start}' AND DATE(o.ORDER_TIMESTAMP) <= '{yesterday}'
              AND (
                  o.TAGS IS NULL
                  OR o.TAGS NOT ILIKE '%Billing cycle%'
                  OR (o.TAGS ILIKE '%Billing cycle #1%' AND o.TAGS NOT ILIKE '%Billing cycle #2%'
                      AND o.TAGS NOT ILIKE '%Billing cycle #3%' AND o.TAGS NOT ILIKE '%Billing cycle #4%'
                      AND o.TAGS NOT ILIKE '%Billing cycle #5%' AND o.TAGS NOT ILIKE '%Billing cycle #6%'
                      AND o.TAGS NOT ILIKE '%Billing cycle #7%' AND o.TAGS NOT ILIKE '%Billing cycle #8%'
                      AND o.TAGS NOT ILIKE '%Billing cycle #9%')
              )
            GROUP BY DATE(o.ORDER_TIMESTAMP), o.ORDER_ID
        )
        SELECT DATE_START, SUM(ORDER_REVENUE) AS NEW_PLUS_REVENUE
        FROM order_tags
        GROUP BY DATE_START
    """.format(category=category, month_minus3_start=month_minus3_start, yesterday=yesterday)).to_pandas()
    df_new_plus_purchase["DATE_START"] = pd.to_datetime(df_new_plus_purchase["DATE_START"]).dt.date

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

        return {
            "New Purchase ROAS": round(new_pv / total_ad_spent, 2) if total_ad_spent > 0 else 0,
            "NEW+ Purchase ROAS": round(new_plus_rev / total_ad_spent, 2) if total_ad_spent > 0 else 0,
            "Just Meta ROAS": round(meta_pv / total_ad_spent, 2) if total_ad_spent > 0 else 0,
            "ROAS Wanted": 0.82,
            "AOV": round(total_sales / total_orders, 2) if total_orders > 0 else 0,
            "New AOV": round(new_pv / new_orders, 2) if new_orders > 0 else 0,
            "CR": f"{round((non_sub_orders / lpv_total * 100), 2) if lpv_total > 0 else 0}%",
            "CPA" : round(total_ad_spent / new_orders, 2) if new_orders > 0 else 0,
            "Blended ROAS": round(all_revenue / total_ad_spent, 2) if total_ad_spent > 0 else 0,
            "Category Blended": round(coffee_pv / total_ad_spent, 2) if total_ad_spent > 0 else 0,
            "Sub Retention Revenue": sub_ret,
        }

    roas_metric_names = ["New Purchase ROAS", "NEW+ Purchase ROAS", "Just Meta ROAS", "ROAS Wanted",
                         "AOV", "New AOV","CPA", "CR", "Blended ROAS", "Category Blended", "Sub Retention Revenue"]
    roas_table_rows = []
    for m in roas_metric_names:
        row = {"Metric": m}
        for name, s, e in periods:
            row[name] = roas_metrics(name, s, e)[m]
        roas_table_rows.append(row)
    df_roas = pd.DataFrame(roas_table_rows)
    roas_compare = build_compare_values(lambda s, e: roas_metrics("", s, e), roas_metric_names)
    render_beige_table(df_roas, selected_col_name=SEL, compare_values=roas_compare)

    # ─── P&L ─────────────────────────────────────────────────────────────────
    st.markdown("### 📊 P&L (USA · FX 90.53 INR/USD · Loop 0.7% of sub sales)")

    df_cogs = session.sql("""
        SELECT "Lineitem sku" AS SKU, "COGS_USD", "Outbound_1_USD", "Storage_1_USD", "LAST_MILE_1_USD"
        FROM VAHDAM_DB.DASHBOARD_TABLES.D2C_USA_BUDGET_DATA
    """).to_pandas()

    df_orders_pnl = session.sql("""
        WITH category_skus AS (
            SELECT "D2C US" AS SKU
            FROM VAHDAM_DB.MAPLEMONK.VAHDAM_FY27_INPUTS_PRODUCT_MAPPING
            WHERE "CATEGORY" = '{category}' AND "D2C US" IS NOT NULL AND "D2C US" != ''
        )
        SELECT
            DATE(o.ORDER_TIMESTAMP) AS DATE_START,
            o.SKU,
            SUM(CASE WHEN o.IS_REFUND = 0 THEN o.NET_SALES_BEFORE_TAX ELSE 0 END)
                - SUM(COALESCE(o.REFUND_VALUE, 0))                       AS LINE_REVENUE,
            SUM(CASE WHEN o.IS_REFUND = 0 THEN o.QUANTITY ELSE 0 END)    AS LINE_QTY,
            COUNT(DISTINCT o.ORDER_ID)                                   AS LINE_ORDERS
        FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUSA_ALL_ORDERS_ITEMS o
        JOIN category_skus cs ON o.SKU = cs.SKU
        WHERE o.ORDER_STATUS != 'CANCELLED'
          AND DATE(o.ORDER_TIMESTAMP) >= '{month_minus3_start}' AND DATE(o.ORDER_TIMESTAMP) <= '{yesterday}'
        GROUP BY DATE(o.ORDER_TIMESTAMP), o.SKU
    """.format(category=category, month_minus3_start=month_minus3_start, yesterday=yesterday)).to_pandas()
    df_orders_pnl["DATE_START"] = pd.to_datetime(df_orders_pnl["DATE_START"]).dt.date

    df_orders_pnl = df_orders_pnl.merge(df_cogs, on="SKU", how="left")
    for _c in ["COGS_USD", "Outbound_1_USD", "Storage_1_USD", "LAST_MILE_1_USD"]:
        df_orders_pnl[_c] = pd.to_numeric(df_orders_pnl[_c], errors="coerce").fillna(0)

    df_orders_pnl["NET_SALES_AFTER_TAX"] = df_orders_pnl["LINE_REVENUE"]   # already net of refunds
    df_orders_pnl["COGS_TOTAL"]      = df_orders_pnl["COGS_USD"] * df_orders_pnl["LINE_QTY"]
    df_orders_pnl["OUTBOUND_TOTAL"]  = df_orders_pnl["Outbound_1_USD"] * df_orders_pnl["LINE_QTY"]
    df_orders_pnl["STORAGE_TOTAL"]   = df_orders_pnl["Storage_1_USD"] * df_orders_pnl["LINE_QTY"]
    df_orders_pnl["LAST_MILE_TOTAL"] = df_orders_pnl["LAST_MILE_1_USD"] * df_orders_pnl["LINE_QTY"]

    # Loop base: subscription net sales (raw, no coffee adj) for this category
    df_loop_base = session.sql("""
        WITH category_skus AS (
            SELECT "D2C US" AS SKU
            FROM VAHDAM_DB.MAPLEMONK.VAHDAM_FY27_INPUTS_PRODUCT_MAPPING
            WHERE "CATEGORY" = '{category}' AND "D2C US" IS NOT NULL AND "D2C US" != ''
        )
        SELECT DATE(o.ORDER_TIMESTAMP) AS DATE_START,
            SUM(o.NET_SALES_BEFORE_TAX) AS SUB_NET_SALES_RAW
        FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUSA_ALL_ORDERS_ITEMS o
        JOIN category_skus cs ON o.SKU = cs.SKU
        WHERE o.ORDER_STATUS != 'CANCELLED'
          AND o.TAGS ILIKE '%Billing Cycle%'
          AND DATE(o.ORDER_TIMESTAMP) >= '{month_minus3_start}' AND DATE(o.ORDER_TIMESTAMP) <= '{yesterday}'
        GROUP BY DATE(o.ORDER_TIMESTAMP)
    """.format(category=category, month_minus3_start=month_minus3_start, yesterday=yesterday)).to_pandas()
    df_loop_base["DATE_START"] = pd.to_datetime(df_loop_base["DATE_START"]).dt.date
    df_loop_base["SUB_NET_SALES_RAW"] = pd.to_numeric(df_loop_base["SUB_NET_SALES_RAW"], errors="coerce").fillna(0.0)

    # PG commission = actual processor fees (FEE), prorated to this category by
    # each order's category share of net sales.
    df_pg_fees = session.sql("""
        WITH category_skus AS (
            SELECT "D2C US" AS SKU
            FROM VAHDAM_DB.MAPLEMONK.VAHDAM_FY27_INPUTS_PRODUCT_MAPPING
            WHERE "CATEGORY" = '{category}' AND "D2C US" IS NOT NULL AND "D2C US" != ''
        ),
        ord AS (
            SELECT o.ORDER_ID, DATE(o.ORDER_TIMESTAMP) AS DATE_START,
                SUM(o.NET_SALES_BEFORE_TAX) AS TOT_NET,
                SUM(CASE WHEN o.SKU IN (SELECT SKU FROM category_skus)
                         THEN o.NET_SALES_BEFORE_TAX ELSE 0 END) AS CAT_NET
            FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUSA_ALL_ORDERS_ITEMS o
            WHERE o.ORDER_STATUS != 'CANCELLED'
              AND DATE(o.ORDER_TIMESTAMP) >= '{m3}' AND DATE(o.ORDER_TIMESTAMP) <= '{y}'
            GROUP BY o.ORDER_ID, DATE(o.ORDER_TIMESTAMP)
        ),
        fee AS (
            SELECT SOURCE_ORDER_ID AS ORDER_ID, SUM(FEE) AS ORDER_FEE
            FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUS_BALANCE_TRANSACTIONS
            WHERE TYPE = 'charge'
            GROUP BY SOURCE_ORDER_ID
        )
        SELECT ord.DATE_START,
            SUM(fee.ORDER_FEE * (CASE WHEN ord.TOT_NET > 0 THEN ord.CAT_NET / ord.TOT_NET ELSE 0 END)) AS PG_FEE
        FROM ord JOIN fee ON fee.ORDER_ID = ord.ORDER_ID
        GROUP BY ord.DATE_START
    """.format(category=category, m3=month_minus3_start, y=yesterday)).to_pandas()
    df_pg_fees["DATE_START"] = pd.to_datetime(df_pg_fees["DATE_START"]).dt.date
    df_pg_fees["PG_FEE"] = pd.to_numeric(df_pg_fees["PG_FEE"], errors="coerce").fillna(0.0)
    
    def pnl_metrics(start, end):
        mask = (df_orders_pnl["DATE_START"] >= start) & (df_orders_pnl["DATE_START"] <= end)
        subset = df_orders_pnl.loc[mask]

        net_sales = round(subset["NET_SALES_AFTER_TAX"].sum(), 2)
        # gross_sales = round(subset["NET_SALES_AFTER_TAX"].sum(), 2)
        # mask_ref = (df_refunds["DATE_START"] >= start) & (df_refunds["DATE_START"] <= end)
        # refunds = round(df_refunds.loc[mask_ref, "REFUND_AMT"].sum(), 2)
        # net_sales = round(gross_sales - refunds, 2)
        
        cogs = round(subset["COGS_TOTAL"].sum(), 2)
        cogs_pct = round((cogs / net_sales * 100), 2) if net_sales > 0 else 0
        outbound = round(subset["OUTBOUND_TOTAL"].sum(), 2)
        outbound_pct = round((outbound / net_sales * 100), 2) if net_sales > 0 else 0
        last_mile = round(subset["LAST_MILE_TOTAL"].sum(), 2)
        last_mile_pct = round((last_mile / net_sales * 100), 2) if net_sales > 0 else 0
        storage = round(subset["STORAGE_TOTAL"].sum(), 2)
        storage_pct = round((storage / net_sales * 100), 2) if net_sales > 0 else 0

        gross_margin = round(net_sales - cogs, 2)

        # PG commission = 2.5% of net sales
        # pg_commission = round(net_sales * PG_COMMISSION_RATE, 2)
        # pg_pct = round((pg_commission / net_sales * 100), 2) if net_sales > 0 else 0
        # PG commission = actual processor fees (FEE), prorated to this category
        mask_pg = (df_pg_fees["DATE_START"] >= start) & (df_pg_fees["DATE_START"] <= end)
        pg_commission = round(df_pg_fees.loc[mask_pg, "PG_FEE"].sum(), 2)
        pg_pct = round((pg_commission / net_sales * 100), 2) if net_sales > 0 else 0

        shopify_costs = 0
        supply_pct = round(((cogs + outbound + last_mile + storage) / net_sales * 100), 2) if net_sales > 0 else 0
        # Loop commission = 0.7% of subscription net sales (raw) — now a CM1 cost
        mask_lb = (df_loop_base["DATE_START"] >= start) & (df_loop_base["DATE_START"] <= end)
        sub_net_sales_raw = round(df_loop_base.loc[mask_lb, "SUB_NET_SALES_RAW"].sum(), 2)
        loop_commission = round(sub_net_sales_raw * LOOP_COMMISSION_RATE, 2)

        cm1 = round(net_sales - cogs - outbound - last_mile - storage - pg_commission - shopify_costs - loop_commission, 2)
        cm1_pct = round((cm1 / net_sales * 100), 2) if net_sales > 0 else 0

        total_ad_spent = sum_spend(df_raw, start, end)
        agency_fees = 1
        software_gross = software_platform_cost_usd(start, end)        # day-wise prorated
        tech_cost = round(software_gross - loop_commission, 2)         # Loop carved out of tech
        cm2 = round(cm1 - total_ad_spent - agency_fees - tech_cost, 2) # Loop NOT re-subtracted

        return {
            "Net Sales (After Tax)": net_sales,
            "COGS": cogs,
            "COGS %": f"{cogs_pct}%",
            "Gross Margin": gross_margin,
            "Outbound": outbound,
            "Outbound %": f"{outbound_pct}%",
            "Last Mile": last_mile,
            "Last Mile %": f"{last_mile_pct}%",
            "Storage": storage,
            "Storage %": f"{storage_pct}%",
            "PG Commission": pg_commission,
            "PG Commission %": f"{pg_pct}%",
            "Shopify Costs": shopify_costs,
            "Supply %": f"{supply_pct}%",
            "Loop Commission": loop_commission,
            "CM1": cm1,
            "CM1 %": f"{cm1_pct}%",
            "Performance Marketing Cost": total_ad_spent,
            "Agency Fees": agency_fees,
            "Software & Platform Cost": tech_cost,
            "CM2": cm2,
            "_Subscription Net Sales (raw)": sub_net_sales_raw,
            "_Software (gross USD)": software_gross,
        }

    pnl_metric_names = ["Net Sales (After Tax)", "COGS", "COGS %",
                        "Gross Margin", "Outbound", "Outbound %",
                        "Last Mile", "Last Mile %", "Storage", "Storage %",
                        "PG Commission", "PG Commission %",
                        "Shopify Costs", "Supply %",
                        "Loop Commission", "CM1", "CM1 %",
                        "Performance Marketing Cost", "Agency Fees",
                        "Software & Platform Cost", "CM2"]

    pnl_period_data = {name: pnl_metrics(s, e) for name, s, e in periods}
    pnl_table_rows = []
    for m in pnl_metric_names:
        row = {"Metric": m}
        for name, _, _ in periods:
            row[name] = pnl_period_data[name][m]
        pnl_table_rows.append(row)
    df_pnl = pd.DataFrame(pnl_table_rows)
    pnl_compare = build_compare_values(lambda s, e: pnl_metrics(s, e), pnl_metric_names)
    render_beige_table(df_pnl, selected_col_name=SEL, compare_values=pnl_compare)

    st.caption(
        "**PG Commission** = 2.5% of net sales. **Loop Commission** = 0.7% × subscription net sales "
        f"({category} orders tagged 'Billing Cycle', raw NET_SALES_BEFORE_TAX, no coffee ×5/6). "
        "**Software & Platform Cost** = fixed monthly tech ($4064 base for May, +10%/mo, USD) **minus** Loop Commission. "
        "CM2 deducts ad spend, agency, Loop and net tech cost."
    )

    with st.expander("🔍 Tech cost build-up — software (gross USD) − Loop Commission"):
        _tc_names = ["Software (gross USD)", "Loop Commission", "Software & Platform Cost", "Subscription Net Sales (raw)"]
        _tc_src = {
            "Software (gross USD)": "_Software (gross USD)",
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
        _tc_compare = build_compare_values(
            lambda s, e: {k: pnl_metrics(s, e)[_tc_src[k]] for k in _tc_names}, _tc_names)
        render_beige_table(pd.DataFrame(_tc_rows), selected_col_name=SEL, compare_values=_tc_compare)

    # ─── COHORT LTV + SUBSCRIPTION RETENTION (store-wide, USD) ────────────────
    _render_cohort(session, tab, yesterday)


def _render_cohort(session, tab, yesterday):
    st.markdown("---")
    st.markdown("## Cohort LTV & Subscription Retention")

    _c1, _c2 = st.columns(2)
    with _c1:
        cohort_from = st.date_input("Cohort window — From", value=yesterday - timedelta(days=29), key=f"cohort_from_{tab}")
    with _c2:
        cohort_to = st.date_input("Cohort window — To", value=yesterday, key=f"cohort_to_{tab}")
    if cohort_from > cohort_to:
        st.error("'From' date must be on or before 'To'.")
        st.stop()

    st.markdown("### Cohort LTV — customers acquired in picker window")
    st.caption("Customer = unique email (lowercased). Net revenue = order total − refunds. Subscription renewals compound into LTV.")

    df_cohort_raw = session.sql(f"""
        WITH cohort_customers AS (
            SELECT LOWER(TRIM(EMAIL)) AS EMAIL, MIN(DATE(ORDER_TIMESTAMP)) AS FIRST_ORDER_DATE
            FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUSA_ALL_ORDERS_ITEMS
            WHERE ORDER_STATUS != 'CANCELLED' AND EMAIL IS NOT NULL AND TRIM(EMAIL) != ''
            GROUP BY LOWER(TRIM(EMAIL))
            HAVING MIN(DATE(ORDER_TIMESTAMP)) >= '{cohort_from}' AND MIN(DATE(ORDER_TIMESTAMP)) <= '{cohort_to}'
        )
        SELECT
            FLOOR(DATEDIFF('day', c.FIRST_ORDER_DATE, DATE(o.ORDER_TIMESTAMP)) / 30) AS MONTH_NUM,
            COUNT(DISTINCT c.EMAIL)               AS ACTIVE_CUSTOMERS,
            COUNT(DISTINCT o.ORDER_ID)            AS ORDERS,
            ROUND(SUM(o.NET_SALES_BEFORE_TAX), 2) AS REVENUE
        FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUSA_ALL_ORDERS_ITEMS o
        JOIN cohort_customers c ON LOWER(TRIM(o.EMAIL)) = c.EMAIL
        WHERE o.ORDER_STATUS != 'CANCELLED'
        GROUP BY MONTH_NUM ORDER BY MONTH_NUM
    """).to_pandas()

    if df_cohort_raw.empty:
        st.info("No customers acquired in the selected window.")
    else:
        cohort_size        = int(df_cohort_raw.loc[df_cohort_raw["MONTH_NUM"] == 0, "ACTIVE_CUSTOMERS"].sum())
        cumulative_revenue = round(float(df_cohort_raw["REVENUE"].sum()), 2)
        ltv_per_customer   = round(cumulative_revenue / cohort_size, 2) if cohort_size else 0.0
        _k1, _k2, _k3 = st.columns(3)
        _k1.metric("Cohort size",        f"{cohort_size:,} unique customers (by email)")
        _k2.metric("Cumulative revenue", f"${cumulative_revenue:,.2f}")
        _k3.metric("LTV per customer",   f"${ltv_per_customer:.2f}")

        _cum_rev = 0.0
        _ltv_rows = []
        for _, _r in df_cohort_raw.iterrows():
            _m = int(_r["MONTH_NUM"]); _rev = round(float(_r["REVENUE"]), 2); _cum_rev += _rev
            _act = int(_r["ACTIVE_CUSTOMERS"])
            _ret = round(_act / cohort_size * 100, 2) if cohort_size else 0.0
            _cltv = round(_cum_rev / cohort_size, 2) if cohort_size else 0.0
            _label = (pd.Timestamp(cohort_from) + relativedelta(months=_m)).strftime("%b %Y")
            _ltv_rows.append({
                "Month since acquisition": f"M{_m} · {_label}",
                "Active customers": _act,
                "Retention": f"{_ret:.2f}%",
                "Orders": int(_r["ORDERS"]),
                "Revenue this month": f"${_rev:,.2f}",
                "Cumulative revenue": f"${_cum_rev:,.2f}",
                "Cumulative LTV": f"${_cltv:.2f}",
            })
        st.dataframe(pd.DataFrame(_ltv_rows), use_container_width=True, hide_index=True)

    # st.markdown("### Subscription Retention — Mₙ rate (30-day plans, USD, picker window)")
    # st.caption(f"Window: {cohort_from.strftime('%b %d, %Y')} → {cohort_to.strftime('%b %d, %Y')} · 30-day plans only · source: Loop subscription contracts")

    # _RET_MAX = 8
    # _sub_lookback = cohort_from - timedelta(days=_RET_MAX * 30)

    # df_sub_starts = session.sql(f"""
    #     SELECT DATE(ORDER_TIMESTAMP) AS START_DATE, COUNT(DISTINCT ORDER_ID) AS SUB_COUNT
    #     FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUSA_ALL_ORDERS_ITEMS
    #     WHERE ORDER_STATUS != 'CANCELLED'
    #       AND TAGS ILIKE '%Billing cycle #1%'
    #       AND (TAGS ILIKE '%30 day%' OR TAGS ILIKE '%30-day%' OR TAGS ILIKE '%monthly%')
    #       AND DATE(ORDER_TIMESTAMP) >= '{_sub_lookback}' AND DATE(ORDER_TIMESTAMP) <= '{cohort_to}'
    #     GROUP BY DATE(ORDER_TIMESTAMP)
    # """).to_pandas()
    # df_sub_starts["START_DATE"] = pd.to_datetime(df_sub_starts["START_DATE"]).dt.date

    # df_renewals = session.sql(f"""
    #     SELECT
    #         REGEXP_SUBSTR(TAGS, 'Billing Cycle #([0-9]+)', 1, 1, 'ie', 1)::INT AS CYCLE_NUM,
    #         COUNT(DISTINCT ORDER_ID)              AS VOL_Y,
    #         ROUND(SUM(NET_SALES_BEFORE_TAX), 2)   AS VOL_REVENUE
    #     FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUSA_ALL_ORDERS_ITEMS
    #     WHERE ORDER_STATUS != 'CANCELLED'
    #       AND TAGS ILIKE '%Billing cycle%' AND TAGS NOT ILIKE '%Billing cycle #1%'
    #       AND (TAGS ILIKE '%30 day%' OR TAGS ILIKE '%30-day%' OR TAGS ILIKE '%monthly%')
    #       AND DATE(ORDER_TIMESTAMP) >= '{cohort_from}' AND DATE(ORDER_TIMESTAMP) <= '{cohort_to}'
    #     GROUP BY CYCLE_NUM ORDER BY CYCLE_NUM
    # """).to_pandas()

    # _ret_rows = []
    # for _n in range(1, _RET_MAX + 1):
    #     _cw_start = cohort_from - timedelta(days=_n * 30)
    #     _cw_end   = cohort_to   - timedelta(days=_n * 30)
    #     _mask_s = (df_sub_starts["START_DATE"] >= _cw_start) & (df_sub_starts["START_DATE"] <= _cw_end)
    #     _cohort_x = int(df_sub_starts.loc[_mask_s, "SUB_COUNT"].sum())
    #     _row_r = df_renewals[df_renewals["CYCLE_NUM"] == _n + 1]
    #     _vol_y = int(_row_r["VOL_Y"].sum())
    #     _vol_rev = round(float(_row_r["VOL_REVENUE"].sum()), 2)
    #     _vol_pct = round(_vol_y / _cohort_x * 100, 2) if _cohort_x else 0.0
    #     _ret_rows.append({
    #         "Mₙ": f"M{_n}",
    #         "Subscriptions started in": f"{_cw_start.strftime('%b %d, %Y')} → {_cw_end.strftime('%b %d, %Y')}",
    #         "Cohort (X)": _cohort_x,
    #         "Vol (Y')": _vol_y,
    #         "Vol %": f"{_vol_pct:.2f}%",
    #         "Vol revenue": f"${_vol_rev:,.2f}",
    #     })
    # st.dataframe(pd.DataFrame(_ret_rows), use_container_width=True, hide_index=True)

def render_overall_pnl(session):
    """US OVERALL P&L — all categories / all campaigns combined, store-wide.
    Tech cost is the single company figure ($4064), counted once (not 3x)."""
    from datetime import datetime
    yesterday = (datetime.today() - timedelta(days=1)).date()
    seven_days_ago = yesterday - timedelta(days=6)
    current_month_start = yesterday.replace(day=1)
    prev_month_end = current_month_start - timedelta(days=1)
    prev_month_start = prev_month_end.replace(day=1)
    month_minus2_end = prev_month_start - timedelta(days=1)
    month_minus2_start = month_minus2_end.replace(day=1)
    month_minus3_end = month_minus2_start - timedelta(days=1)
    month_minus3_start = month_minus3_end.replace(day=1)

    periods = [
        ("Last 7 Days", seven_days_ago, yesterday),
        ("Month TD", current_month_start, yesterday),
        (prev_month_start.strftime("%b %Y"), prev_month_start, prev_month_end),
        (month_minus2_start.strftime("%b %Y"), month_minus2_start, month_minus2_end),
        (month_minus3_start.strftime("%b %Y"), month_minus3_start, month_minus3_end),
    ]

    _sel_cmp_to   = seven_days_ago - timedelta(days=1)
    _sel_cmp_from = _sel_cmp_to - timedelta(days=6)
    _mtd_days     = (yesterday - current_month_start).days + 1
    _mtd_cmp_to   = min(prev_month_start + timedelta(days=_mtd_days - 1), prev_month_end)
    compare_periods = {
        "Last 7 Days":                        (_sel_cmp_from, _sel_cmp_to),
        "Month TD":                           (prev_month_start, _mtd_cmp_to),
        prev_month_start.strftime("%b %Y"):   (month_minus2_start, month_minus2_end),
        month_minus2_start.strftime("%b %Y"): (month_minus3_start, month_minus3_end),
        month_minus3_start.strftime("%b %Y"): None,
    }

    def build_compare_values(value_fn, names):
        cv = {}
        for col, win in compare_periods.items():
            if win is None:
                continue
            d = value_fn(win[0], win[1])
            cv[col] = {m: d[m] for m in names}
        return cv

    SEL = "Last 7 Days"

    # ── Total ad spend (all campaigns: Meta USA + Google US) ──────────────────
    df_raw = session.sql("""
        SELECT DATE_START, SPEND
        FROM (
            SELECT DATE_START, SPEND
            FROM VAHDAM_DB.MAPLEMONK.META_USA_CUSTOMCAMPAIGNS_DATA
            WHERE DATE_START >= '{m3}' AND DATE_START <= '{y}'
            UNION ALL
            SELECT "segments.date" AS DATE_START, "metrics.cost_micros" / 1000000.0 AS SPEND
            FROM VAHDAM_DB.MAPLEMONK.GOOGLE_ADS_US_CAMPAIGN_DATA
            WHERE "segments.date" >= '{m3}' AND "segments.date" <= '{y}'
        )
    """.format(m3=month_minus3_start, y=yesterday)).to_pandas()
    df_raw["DATE_START"] = pd.to_datetime(df_raw["DATE_START"]).dt.date

    def sum_spend(df, start, end):
        mask = (df["DATE_START"] >= start) & (df["DATE_START"] <= end)
        return round(df.loc[mask, "SPEND"].sum(), 2)

    # ── Per-unit costs ────────────────────────────────────────────────────────
    df_cogs = session.sql("""
        SELECT "Lineitem sku" AS SKU, "COGS_USD", "Outbound_1_USD", "Storage_1_USD", "LAST_MILE_1_USD"
        FROM VAHDAM_DB.DASHBOARD_TABLES.D2C_USA_BUDGET_DATA
    """).to_pandas()

    # ── All orders / all SKUs (store-wide) ────────────────────────────────────
    df_orders_pnl = session.sql("""
        SELECT
            DATE(o.ORDER_TIMESTAMP) AS DATE_START,
            o.SKU,
            SUM(CASE WHEN o.IS_REFUND = 0 THEN o.NET_SALES_BEFORE_TAX ELSE 0 END)
                - SUM(COALESCE(o.REFUND_VALUE, 0))                       AS LINE_REVENUE,
            SUM(CASE WHEN o.IS_REFUND = 0 THEN o.QUANTITY ELSE 0 END)    AS LINE_QTY
        FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUSA_ALL_ORDERS_ITEMS o
        WHERE o.ORDER_STATUS != 'CANCELLED'
          AND DATE(o.ORDER_TIMESTAMP) >= '{m3}' AND DATE(o.ORDER_TIMESTAMP) <= '{y}'
        GROUP BY DATE(o.ORDER_TIMESTAMP), o.SKU
    """.format(m3=month_minus3_start, y=yesterday)).to_pandas()
    df_orders_pnl["DATE_START"] = pd.to_datetime(df_orders_pnl["DATE_START"]).dt.date

    df_orders_pnl = df_orders_pnl.merge(df_cogs, on="SKU", how="left")
    for _c in ["COGS_USD", "Outbound_1_USD", "Storage_1_USD", "LAST_MILE_1_USD"]:
        df_orders_pnl[_c] = pd.to_numeric(df_orders_pnl[_c], errors="coerce").fillna(0)

    df_orders_pnl["NET_SALES_AFTER_TAX"] = df_orders_pnl["LINE_REVENUE"]   # already net of refunds
    df_orders_pnl["COGS_TOTAL"]      = df_orders_pnl["COGS_USD"] * df_orders_pnl["LINE_QTY"]
    df_orders_pnl["OUTBOUND_TOTAL"]  = df_orders_pnl["Outbound_1_USD"] * df_orders_pnl["LINE_QTY"]
    df_orders_pnl["STORAGE_TOTAL"]   = df_orders_pnl["Storage_1_USD"] * df_orders_pnl["LINE_QTY"]
    df_orders_pnl["LAST_MILE_TOTAL"] = df_orders_pnl["LAST_MILE_1_USD"] * df_orders_pnl["LINE_QTY"]

    # ── Loop base: store-wide subscription net sales (raw) ────────────────────
    df_loop_base = session.sql("""
        SELECT DATE(o.ORDER_TIMESTAMP) AS DATE_START,
            SUM(o.NET_SALES_BEFORE_TAX) AS SUB_NET_SALES_RAW
        FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUSA_ALL_ORDERS_ITEMS o
        WHERE o.ORDER_STATUS != 'CANCELLED'
          AND o.TAGS ILIKE '%Billing Cycle%'
          AND DATE(o.ORDER_TIMESTAMP) >= '{m3}' AND DATE(o.ORDER_TIMESTAMP) <= '{y}'
        GROUP BY DATE(o.ORDER_TIMESTAMP)
    """.format(m3=month_minus3_start, y=yesterday)).to_pandas()
    df_loop_base["DATE_START"] = pd.to_datetime(df_loop_base["DATE_START"]).dt.date
    df_loop_base["SUB_NET_SALES_RAW"] = pd.to_numeric(df_loop_base["SUB_NET_SALES_RAW"], errors="coerce").fillna(0.0)

    # PG commission = actual processor fees (FEE), store-wide, by order date
    df_pg_fees = session.sql("""
        SELECT DATE(o.ORDER_TIMESTAMP) AS DATE_START, SUM(bt.FEE) AS PG_FEE
        FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUS_BALANCE_TRANSACTIONS bt
        JOIN (
            SELECT DISTINCT ORDER_ID, ORDER_TIMESTAMP
            FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUSA_ALL_ORDERS_ITEMS
            WHERE ORDER_STATUS != 'CANCELLED'
        ) o ON o.ORDER_ID = bt.SOURCE_ORDER_ID
        WHERE bt.TYPE = 'charge'
          AND DATE(o.ORDER_TIMESTAMP) >= '{m3}' AND DATE(o.ORDER_TIMESTAMP) <= '{y}'
        GROUP BY DATE(o.ORDER_TIMESTAMP)
    """.format(m3=month_minus3_start, y=yesterday)).to_pandas()
    df_pg_fees["DATE_START"] = pd.to_datetime(df_pg_fees["DATE_START"]).dt.date
    df_pg_fees["PG_FEE"] = pd.to_numeric(df_pg_fees["PG_FEE"], errors="coerce").fillna(0.0)
    
    def pnl_metrics(start, end):
        mask = (df_orders_pnl["DATE_START"] >= start) & (df_orders_pnl["DATE_START"] <= end)
        subset = df_orders_pnl.loc[mask]

        net_sales = round(subset["NET_SALES_AFTER_TAX"].sum(), 2)
        # mask_ref = (df_refunds["DATE_START"] >= start) & (df_refunds["DATE_START"] <= end)
        # refunds = round(df_refunds.loc[mask_ref, "REFUND_AMT"].sum(), 2)
        # net_sales = round(subset["NET_SALES_AFTER_TAX"].sum() - refunds, 2)
        
        cogs = round(subset["COGS_TOTAL"].sum(), 2)
        cogs_pct = round((cogs / net_sales * 100), 2) if net_sales > 0 else 0
        outbound = round(subset["OUTBOUND_TOTAL"].sum(), 2)
        outbound_pct = round((outbound / net_sales * 100), 2) if net_sales > 0 else 0
        last_mile = round(subset["LAST_MILE_TOTAL"].sum(), 2)
        last_mile_pct = round((last_mile / net_sales * 100), 2) if net_sales > 0 else 0
        storage = round(subset["STORAGE_TOTAL"].sum(), 2)
        storage_pct = round((storage / net_sales * 100), 2) if net_sales > 0 else 0

        gross_margin = round(net_sales - cogs, 2)
        # pg_commission = round(net_sales * PG_COMMISSION_RATE, 2)
        # pg_pct = round((pg_commission / net_sales * 100), 2) if net_sales > 0 else 0
        mask_pg = (df_pg_fees["DATE_START"] >= start) & (df_pg_fees["DATE_START"] <= end)
        pg_commission = round(df_pg_fees.loc[mask_pg, "PG_FEE"].sum(), 2)
        pg_pct = round((pg_commission / net_sales * 100), 2) if net_sales > 0 else 0

        shopify_costs = 0
        supply_pct = round(((cogs + outbound + last_mile + storage) / net_sales * 100), 2) if net_sales > 0 else 0
        # Loop commission = 0.7% of subscription net sales (raw) — now a CM1 cost
        mask_lb = (df_loop_base["DATE_START"] >= start) & (df_loop_base["DATE_START"] <= end)
        sub_net_sales_raw = round(df_loop_base.loc[mask_lb, "SUB_NET_SALES_RAW"].sum(), 2)
        loop_commission = round(sub_net_sales_raw * LOOP_COMMISSION_RATE, 2)

        cm1 = round(net_sales - cogs - outbound - last_mile - storage - pg_commission - shopify_costs - loop_commission, 2)
        cm1_pct = round((cm1 / net_sales * 100), 2) if net_sales > 0 else 0

        total_ad_spent = sum_spend(df_raw, start, end)
        agency_fees = 1
        software_gross = software_platform_cost_usd(start, end)        # day-wise prorated
        tech_cost = round(software_gross - loop_commission, 2)         # Loop carved out of tech
        cm2 = round(cm1 - total_ad_spent - agency_fees - tech_cost, 2) # Loop NOT re-subtracted

        return {
            "Net Sales (After Tax)": net_sales,
            "COGS": cogs, "COGS %": f"{cogs_pct}%",
            "Gross Margin": gross_margin,
            "Outbound": outbound, "Outbound %": f"{outbound_pct}%",
            "Last Mile": last_mile, "Last Mile %": f"{last_mile_pct}%",
            "Storage": storage, "Storage %": f"{storage_pct}%",
            "PG Commission": pg_commission, "PG Commission %": f"{pg_pct}%",
            "Shopify Costs": shopify_costs, "Supply %": f"{supply_pct}%",
            "Loop Commission": loop_commission,
            "CM1": cm1,
            "CM1 %": f"{cm1_pct}%",
            "Performance Marketing Cost": total_ad_spent,
            "Agency Fees": agency_fees,
            "Software & Platform Cost": tech_cost,
            "CM2": cm2,
            "_Subscription Net Sales (raw)": sub_net_sales_raw,
            "_Software (gross USD)": software_gross,
        }

    pnl_metric_names = ["Net Sales (After Tax)", "COGS", "COGS %",
                        "Gross Margin", "Outbound", "Outbound %",
                        "Last Mile", "Last Mile %", "Storage", "Storage %",
                        "PG Commission", "PG Commission %",
                        "Shopify Costs", "Supply %",
                        "Loop Commission", "CM1", "CM1 %",
                        "Performance Marketing Cost", "Agency Fees",
                        "Software & Platform Cost", "CM2"]

    st.subheader("📊 US OVERALL P&L — all categories combined")
    st.markdown("### P&L (USA store-wide · all campaigns · Loop 0.7% of sub sales)")

    pnl_period_data = {name: pnl_metrics(s, e) for name, s, e in periods}
    rows = []
    for m in pnl_metric_names:
        row = {"Metric": m}
        for name, _, _ in periods:
            row[name] = pnl_period_data[name][m]
        rows.append(row)
    df_pnl = pd.DataFrame(rows)
    pnl_compare = build_compare_values(lambda s, e: pnl_metrics(s, e), pnl_metric_names)
    render_beige_table(df_pnl, selected_col_name=SEL, compare_values=pnl_compare)

    st.caption(
        "Store-wide US P&L: every order / SKU, total Meta+Google spend. "
        "**PG** = 2.5% of net sales · **Loop** = 0.7% of store-wide subscription net sales (raw) · "
        "**Software** = single company tech ($4064/mo, +10%/mo, USD) counted once, minus Loop. "
        "CM2 deducts ad spend, agency, Loop and net tech."
    )

    with st.expander("🔍 Tech cost build-up — software (gross USD) − Loop Commission"):
        _tc_names = ["Software (gross USD)", "Loop Commission", "Software & Platform Cost", "Subscription Net Sales (raw)"]
        _tc_src = {
            "Software (gross USD)": "_Software (gross USD)",
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
        _tc_compare = build_compare_values(
            lambda s, e: {k: pnl_metrics(s, e)[_tc_src[k]] for k in _tc_names}, _tc_names)
        render_beige_table(pd.DataFrame(_tc_rows), selected_col_name=SEL, compare_values=_tc_compare)


def render_category_revenue(session):
    """US category net revenue (Coffee/Tea/Supplements), FULL calendar months:
    last completed month vs prior month (MoM) and same month last year (YoY).
    Same net-revenue logic as the tabs (IS_REFUND=0 net - REFUND_VALUE),
    so each category ties exactly to that tab's monthly column."""
    from datetime import datetime
    yesterday = (datetime.today() - timedelta(days=1)).date()

    cur_first = yesterday.replace(day=1)
    m0_end   = cur_first - timedelta(days=1)          # last completed month: end
    m0_start = m0_end.replace(day=1)                  #   "          "       : start
    mm_end   = m0_start - timedelta(days=1)           # prior month (MoM)
    mm_start = mm_end.replace(day=1)
    ly_start = m0_start - relativedelta(years=1)      # same month last year (YoY)
    ly_end   = ly_start.replace(day=calendar.monthrange(ly_start.year, ly_start.month)[1])

    df = session.sql("""
        WITH map AS (
            SELECT DISTINCT "D2C US" AS SKU, "CATEGORY" AS CAT
            FROM VAHDAM_DB.MAPLEMONK.VAHDAM_FY27_INPUTS_PRODUCT_MAPPING
            WHERE "CATEGORY" IN ('Coffee','Tea and Botanicals','Supplements')
              AND "D2C US" IS NOT NULL AND "D2C US" != ''
        )
        SELECT DATE(o.ORDER_TIMESTAMP) AS DATE_START, m.CAT,
            ROUND(SUM(CASE WHEN o.IS_REFUND = 0 THEN o.NET_SALES_BEFORE_TAX ELSE 0 END)
                  - SUM(COALESCE(o.REFUND_VALUE, 0)), 2) AS NET_REV
        FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUSA_ALL_ORDERS_ITEMS o
        JOIN map m ON m.SKU = o.SKU
        WHERE o.ORDER_STATUS != 'CANCELLED'
          AND DATE(o.ORDER_TIMESTAMP) >= '{ly}' AND DATE(o.ORDER_TIMESTAMP) <= '{m0e}'
        GROUP BY DATE(o.ORDER_TIMESTAMP), m.CAT
    """.format(ly=ly_start, m0e=m0_end)).to_pandas()
    df["DATE_START"] = pd.to_datetime(df["DATE_START"]).dt.date
    df["NET_REV"] = pd.to_numeric(df["NET_REV"], errors="coerce").fillna(0.0)

    def wsum(cat, s, e):
        m = (df["CAT"] == cat) & (df["DATE_START"] >= s) & (df["DATE_START"] <= e)
        return round(float(df.loc[m, "NET_REV"].sum()), 2)

    def pct_cell(curr, prev):
        if not prev:
            return "â€”"
        p = (curr - prev) / abs(prev) * 100
        cls = "delta-up" if p >= 0 else "delta-down"
        arr = "â–²" if p >= 0 else "â–¼"
        return f"<span class='{cls}'>{arr} {p:+.1f}%</span>"

    c0  = m0_start.strftime("%b %Y")   # last completed month
    cmm = mm_start.strftime("%b %Y")   # prior month
    cly = ly_start.strftime("%b %Y")   # same month last year

    st.subheader("ðŸ“ˆ US â€” Category Revenue Â· MoM & YoY")
    st.caption(
        f"Net revenue (refund-adjusted), **full calendar months**. "
        f"{c0} vs {cmm} (MoM) and {cly} (YoY). Each figure ties to that category tab's {c0} column."
    )

    disp = {"Coffee": "â˜• Coffee", "Tea and Botanicals": "ðŸµ Tea", "Supplements": "ðŸ’Š Supplements"}
    rows, t0, tm, tl = [], 0.0, 0.0, 0.0
    for cat, label in disp.items():
        v0, vm, vl = wsum(cat, m0_start, m0_end), wsum(cat, mm_start, mm_end), wsum(cat, ly_start, ly_end)
        t0 += v0; tm += vm; tl += vl
        rows.append({"Metric": label, c0: f"${v0:,.0f}", cmm: f"${vm:,.0f}",
                     "MoM %": pct_cell(v0, vm), cly: f"${vl:,.0f}", "YoY %": pct_cell(v0, vl)})
    rows.append({"Metric": "Total", c0: f"${t0:,.0f}", cmm: f"${tm:,.0f}",
                 "MoM %": pct_cell(t0, tm), cly: f"${tl:,.0f}", "YoY %": pct_cell(t0, tl)})

    render_beige_table(pd.DataFrame(rows), selected_col_name=c0, compare_values={})
