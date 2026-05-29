"""
D2C UK dashboard — integrated into the main Vahdam dashboard as the
**D2C** top-level tab. Entry point: ``render(run_query)``.

`run_query(sql) -> pd.DataFrame` is supplied by *app.py* so this module
reuses the existing Snowflake connection / retry / friendly-error logic
instead of opening its own.

The whole D2C dashboard body lives inside ``render`` so its CSS theme
(beige) is injected only when the D2C tab is active. Once the user
clicks back to Amazon, Streamlit's rerun rebuilds the DOM without this
module's CSS and the Amazon theme reasserts itself.

Original source: ``D2C_UK.py`` by Yakshit Bansal (May 2026). Adapted
here so that all ``session.sql(...).to_pandas()`` calls go through
``run_query`` and the module is importable from *app.py*.
"""
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta


def render(run_query):
    """Render the D2C UK dashboard. `run_query(sql)` is the helper from
    *app.py* that executes a SQL string against Snowflake and returns a
    pandas DataFrame with uppercase column names."""

    # ─── D2C THEME (Amazon-matched cream/green/saffron) ──────────────────────
    # Inherits the main app's .page-title / .section-hdr / .pnl-strip CSS
    # so the D2C tab visually reads as the same product. Below we add a
    # restyled comparison-table class (.vahdam-d2c-table) replacing the
    # old brown beige tables — same palette as the Amazon Sub-Cat tables.
    st.markdown("""
    <style>
    .vahdam-d2c-table {
        width: 100%; border-collapse: separate; border-spacing: 0;
        background: #FFFFFF; border-radius: 10px; overflow: hidden;
        border: 1px solid #d6ccba; border-top: 3px solid #004A2B;
        font-family: 'Inter', 'Proxima Nova', Arial, sans-serif;
        font-size: 13px; color: #171717;
        box-shadow: 0 2px 8px rgba(0,74,43,0.08);
        margin: 8px 0 20px 0;
    }
    .vahdam-d2c-table th {
        background: linear-gradient(180deg, #004A2B 0%, #2E7D32 100%);
        color: #FBF5EA; padding: 11px 14px; text-align: left;
        font-weight: 700; letter-spacing: 0.4px; font-size: 12px;
        text-transform: uppercase;
        border-bottom: 2px solid #AB8743;
    }
    .vahdam-d2c-table th.selected-col {
        background: linear-gradient(180deg, #AB8743 0%, #7a5c00 100%);
        color: #FBF5EA;
    }
    .vahdam-d2c-table td {
        padding: 10px 14px; border-bottom: 1px solid #ede4d0;
        color: #1a1a1a; vertical-align: middle;
    }
    .vahdam-d2c-table tr:nth-child(even) td { background: #faf5ea; }
    .vahdam-d2c-table tr:hover td { background: #f4eed8; transition: background 0.18s ease; }
    .vahdam-d2c-table td.selected-col {
        background: #fef3d6 !important; font-weight: 600; color: #5a4d35;
    }
    .vahdam-d2c-table td.metric-name {
        font-weight: 700; color: #004A2B; background: #f4eed8;
        letter-spacing: 0.2px;
    }
    .delta-up   { color: #1a7a3e; font-weight: 700; font-size: 11px; margin-left: 6px; }
    .delta-down { color: #8b1a1a; font-weight: 700; font-size: 11px; margin-left: 6px; }
    .delta-flat { color: #7a6a50; font-weight: 600; font-size: 11px; margin-left: 6px; }
    </style>
    """, unsafe_allow_html=True)

    snapshot_time = datetime.now().strftime("%d %b %Y · %H:%M:%S")
    st.markdown('<div class="page-title">D2C &mdash; United Kingdom</div>',
                 unsafe_allow_html=True)
    st.markdown(
        f'<div class="page-sub">Snapshot {snapshot_time} '
        f'&nbsp;·&nbsp; Currency: <b>GBP (£)</b> '
        f'&nbsp;·&nbsp; Source: Shopify UK + Meta Ads + Google Ads'
        f'</div>',
        unsafe_allow_html=True)

    st.info(
        "The 4 month columns are literal and never change. "
        "The **Selected Range** column at left reflects the date-range picker below "
        "(default: Last 7 Days). Each value shows a % change vs. the next-older "
        "period — green ▲ for increase, red ▼ for decrease. Cohort LTV + Retention "
        "sections below also follow the picker."
    )

    yesterday = (datetime.today() - timedelta(days=1)).date()

    # ─── DATE RANGE PICKER ───────────────────────────────────────────────────
    st.markdown('<div class="section-hdr">📅 Date Range</div>',
                 unsafe_allow_html=True)
    _PRESETS = {
        "Last 7 Days":  7,
        "Last 14 Days": 14,
        "Last 30 Days": 30,
        "Last 60 Days": 60,
        "Last 90 Days": 90,
        "Custom":       None,
    }
    if "d2c_selected_preset" not in st.session_state:
        st.session_state.d2c_selected_preset = "Last 7 Days"
    if "d2c_range_from" not in st.session_state:
        st.session_state.d2c_range_from = yesterday - timedelta(days=6)
    if "d2c_range_to" not in st.session_state:
        st.session_state.d2c_range_to = yesterday

    _pr_cols = st.columns(len(_PRESETS))
    for _i, (_lbl, _days) in enumerate(_PRESETS.items()):
        with _pr_cols[_i]:
            if st.button(_lbl, use_container_width=True,
                         type="primary" if st.session_state.d2c_selected_preset == _lbl else "secondary",
                         key=f"d2c_preset_{_lbl}"):
                st.session_state.d2c_selected_preset = _lbl
                if _days is not None:
                    st.session_state.d2c_range_to = yesterday
                    st.session_state.d2c_range_from = yesterday - timedelta(days=_days - 1)
                st.rerun()

    if st.session_state.d2c_selected_preset == "Custom":
        _dc1, _dc2 = st.columns(2)
        with _dc1:
            st.session_state.d2c_range_from = st.date_input(
                "From", value=st.session_state.d2c_range_from, key="d2c_custom_from")
        with _dc2:
            st.session_state.d2c_range_to = st.date_input(
                "To", value=st.session_state.d2c_range_to, key="d2c_custom_to")
        if st.session_state.d2c_range_from > st.session_state.d2c_range_to:
            st.error("'From' must be on or before 'To'.")
            st.stop()

    selected_from = st.session_state.d2c_range_from
    selected_to   = st.session_state.d2c_range_to
    _days_in_range = (selected_to - selected_from).days + 1
    selected_label = (f"{st.session_state.d2c_selected_preset} "
                      f"({selected_from.strftime('%b %d')} → {selected_to.strftime('%b %d')})")
    st.caption(f"📊 Showing **{selected_label}** · {_days_in_range} days")
    st.markdown("---")

    seven_days_ago      = selected_from
    current_month_start = yesterday.replace(day=1)
    prev_month_end      = current_month_start - timedelta(days=1)
    prev_month_start    = prev_month_end.replace(day=1)
    month_minus2_end    = prev_month_start - timedelta(days=1)
    month_minus2_start  = month_minus2_end.replace(day=1)
    month_minus3_end    = month_minus2_start - timedelta(days=1)
    month_minus3_start  = month_minus3_end.replace(day=1)

    data_lower_bound = min(month_minus3_start, selected_from)
    month_minus3_start_q = data_lower_bound

    df_raw = run_query(f"""
        SELECT DATE_START, SPEND
        FROM (
            SELECT DATE_START, SPEND
            FROM VAHDAM_DB.MAPLEMONK.META_UK_CUSTOMCAMPAIGNS_DATA
            WHERE DATE_START >= '{month_minus3_start_q}' AND DATE_START <= '{yesterday}'
            UNION ALL
            SELECT "segments.date" AS DATE_START, "metrics.cost_micros" / 1000000.0 AS SPEND
            FROM VAHDAM_DB.MAPLEMONK.GOOGLE_ADS_UK_CAMPAIGN_DATA
            WHERE "segments.date" >= '{month_minus3_start_q}' AND "segments.date" <= '{yesterday}'
        )
    """)
    df_raw["DATE_START"] = pd.to_datetime(df_raw["DATE_START"]).dt.date

    def sum_spend(df, start, end):
        mask = (df["DATE_START"] >= start) & (df["DATE_START"] <= end)
        return round(df.loc[mask, "SPEND"].sum(), 2)

    # ─── HELPERS for HTML tables with %-change deltas ────────────────────────
    def _to_num(v):
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            s = v.replace("£", "").replace("$", "").replace(",", "").replace("%", "").strip()
            try:
                return float(s)
            except Exception:
                return None
        return None

    def _delta_html(curr, prev):
        c, p = _to_num(curr), _to_num(prev)
        if c is None or p is None or p == 0:
            return ""
        pct = (c - p) / abs(p) * 100
        if abs(pct) < 0.05:
            return f"<span class='delta-flat'>● {pct:+.1f}%</span>"
        if pct > 0:
            return f"<span class='delta-up'>▲ {pct:+.1f}%</span>"
        return f"<span class='delta-down'>▼ {pct:+.1f}%</span>"

    def render_beige_table(df, selected_col_name=None):
        cols = list(df.columns)
        period_cols = [c for c in cols if c != "Metric"]
        html = ["<table class='vahdam-d2c-table'><thead><tr>"]
        html.append("<th>Metric</th>")
        for c in period_cols:
            cls = "selected-col" if c == selected_col_name else ""
            html.append(f"<th class='{cls}'>{c}</th>")
        html.append("</tr></thead><tbody>")
        for _, row in df.iterrows():
            html.append("<tr>")
            html.append(f"<td class='metric-name'>{row['Metric']}</td>")
            for i, c in enumerate(period_cols):
                val = row[c]
                prev_val = row[period_cols[i + 1]] if i + 1 < len(period_cols) else None
                delta = _delta_html(val, prev_val) if prev_val is not None else ""
                cls = "selected-col" if c == selected_col_name else ""
                html.append(f"<td class='{cls}'>{val}{delta}</td>")
            html.append("</tr>")
        html.append("</tbody></table>")
        st.markdown("".join(html), unsafe_allow_html=True)

    metrics_data = {
        "Metric": ["Total Ad Spent"],
        selected_label:                       [sum_spend(df_raw, seven_days_ago, yesterday)],
        "Month TD":                            [sum_spend(df_raw, current_month_start, yesterday)],
        prev_month_start.strftime("%b %Y"):    [sum_spend(df_raw, prev_month_start, prev_month_end)],
        month_minus2_start.strftime("%b %Y"):  [sum_spend(df_raw, month_minus2_start, month_minus2_end)],
        month_minus3_start.strftime("%b %Y"):  [sum_spend(df_raw, month_minus3_start, month_minus3_end)],
    }
    df_metrics = pd.DataFrame(metrics_data)
    st.markdown('<div class="section-hdr">💰 Metrics Summary</div>',
                 unsafe_allow_html=True)
    render_beige_table(df_metrics, selected_col_name=selected_label)

    # ─── META PERFORMANCE ────────────────────────────────────────────────────
    st.markdown('<div class="section-hdr">📈 Meta Performance '
                 '<span style="font-size:12px;color:#7a6a50;font-weight:500;">'
                 '— AWAR campaigns excluded</span></div>',
                 unsafe_allow_html=True)

    df_meta = run_query(f"""
        SELECT
            DATE_START,
            IMPRESSIONS,
            INLINE_LINK_CLICKS AS CLICKS,
            SPEND,
            NVL(GET(FILTER(ACTIONS, a -> a:action_type::STRING = 'landing_page_view')[0], 'value')::FLOAT, 0) AS LANDING_PAGE_VIEWS,
            NVL(GET(FILTER(ACTIONS, a -> a:action_type::STRING = 'offsite_conversion.fb_pixel_initiate_checkout')[0], 'value')::FLOAT, 0) AS CHECKOUTS,
            NVL(GET(FILTER(ACTIONS, a -> a:action_type::STRING = 'offsite_conversion.fb_pixel_purchase')[0], 'value')::FLOAT, 0) AS PURCHASES
        FROM VAHDAM_DB.MAPLEMONK.META_UK_CUSTOMCAMPAIGNS_DATA
        WHERE DATE_START >= '{month_minus3_start_q}' AND DATE_START <= '{yesterday}'
          AND CAMPAIGN_NAME NOT ILIKE '%AWAR%'
    """)
    df_meta["DATE_START"] = pd.to_datetime(df_meta["DATE_START"]).dt.date

    def meta_metrics(df, start, end):
        mask = (df["DATE_START"] >= start) & (df["DATE_START"] <= end)
        subset = df.loc[mask]
        impressions = subset["IMPRESSIONS"].sum()
        clicks      = subset["CLICKS"].sum()
        spend       = subset["SPEND"].sum()
        lpv         = subset["LANDING_PAGE_VIEWS"].sum()
        checkouts   = subset["CHECKOUTS"].sum()
        purchases   = subset["PURCHASES"].sum()
        lpv_pct           = (lpv / clicks * 100) if clicks > 0 else 0
        cpm               = (spend / impressions * 1000) if impressions > 0 else 0
        cpc               = (spend / clicks) if clicks > 0 else 0
        ctr               = (clicks / impressions * 100) if impressions > 0 else 0
        cost_per_checkout = (spend / checkouts) if checkouts > 0 else 0
        cpa               = (spend / purchases) if purchases > 0 else 0
        return {
            "Impressions":       round(impressions),
            "Clicks":            round(clicks),
            "Landing Page":      round(lpv),
            "LPV %":             f"{lpv_pct:.2f}%",
            "Checkouts":         round(checkouts),
            "Average CPM":       round(cpm, 2),
            "Average CPC":       round(cpc, 2),
            "CTR":               f"{ctr:.2f}%",
            "Cost Per Checkout": round(cost_per_checkout, 2),
            "Purchases":         round(purchases),
            "CPA":               round(cpa, 2),
        }

    periods = [
        (selected_label,                        seven_days_ago,     yesterday),
        ("Month TD",                            current_month_start, yesterday),
        (prev_month_start.strftime("%b %Y"),    prev_month_start,    prev_month_end),
        (month_minus2_start.strftime("%b %Y"),  month_minus2_start,  month_minus2_end),
        (month_minus3_start.strftime("%b %Y"),  month_minus3_start,  month_minus3_end),
    ]

    metric_names = ["Impressions", "Clicks", "Landing Page", "LPV %", "Checkouts",
                    "Average CPM", "Average CPC", "CTR", "Cost Per Checkout",
                    "Purchases", "CPA"]
    period_data = {name: meta_metrics(df_meta, start, end) for name, start, end in periods}
    perf_rows = []
    for m in metric_names:
        row = {"Metric": m}
        for name, _, _ in periods:
            row[name] = period_data[name][m]
        perf_rows.append(row)
    df_perf = pd.DataFrame(perf_rows)
    render_beige_table(df_perf, selected_col_name=selected_label)

    # ─── REVENUE ─────────────────────────────────────────────────────────────
    st.markdown('<div class="section-hdr">💷 Revenue '
                 '<span style="font-size:12px;color:#7a6a50;font-weight:500;">'
                 '— Shopify orders · Coffee = any order containing a coffee SKU'
                 '</span></div>',
                 unsafe_allow_html=True)

    df_meta_pv = run_query(f"""
        SELECT
            DATE_START,
            NVL(GET(FILTER(ACTION_VALUES, a -> a:action_type::STRING = 'offsite_conversion.fb_pixel_purchase')[0], 'value')::FLOAT, 0) AS META_PURCHASE_VALUE
        FROM VAHDAM_DB.MAPLEMONK.META_UK_CUSTOMCAMPAIGNS_DATA
        WHERE DATE_START >= '{month_minus3_start_q}' AND DATE_START <= '{yesterday}'
          AND CAMPAIGN_NAME NOT ILIKE '%AWAR%'
    """)
    df_meta_pv["DATE_START"] = pd.to_datetime(df_meta_pv["DATE_START"]).dt.date

    df_shopify = run_query(f"""
        WITH coffee_orders AS (
            SELECT DISTINCT ORDER_ID
            FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUK_ALL_ORDERS_ITEMS
            WHERE ORDER_STATUS != 'CANCELLED'
              AND DATE(ORDER_TIMESTAMP) >= '{month_minus3_start_q}'
              AND DATE(ORDER_TIMESTAMP) <= '{yesterday}'
              AND SKU ILIKE '%COFFEE%'
        ),
        first_orders AS (
            SELECT ORDER_ID, ORDER_NAME,
                ROW_NUMBER() OVER (PARTITION BY EMAIL ORDER BY ORDER_TIMESTAMP, ORDER_ID) AS RN
            FROM (
                SELECT DISTINCT ORDER_ID, ORDER_NAME, EMAIL, ORDER_TIMESTAMP
                FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUK_ALL_ORDERS_ITEMS
                WHERE ORDER_STATUS != 'CANCELLED'
            )
        ),
        order_summary AS (
            SELECT
                DATE(ORDER_TIMESTAMP) AS DATE_START,
                ORDER_ID,
                SUM(NET_SALES_BEFORE_TAX) AS ORDER_VALUE
            FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUK_ALL_ORDERS_ITEMS
            WHERE ORDER_STATUS != 'CANCELLED'
              AND DATE(ORDER_TIMESTAMP) >= '{month_minus3_start_q}'
              AND DATE(ORDER_TIMESTAMP) <= '{yesterday}'
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
    """)
    df_shopify["DATE_START"] = pd.to_datetime(df_shopify["DATE_START"]).dt.date

    def sum_col(df, col, start, end):
        mask = (df["DATE_START"] >= start) & (df["DATE_START"] <= end)
        return round(df.loc[mask, col].sum(), 2)

    rev_rows = []
    for period_name, start, end in periods:
        rev_rows.append({
            "period":                       period_name,
            "Meta Purchase Value":          sum_col(df_meta_pv, "META_PURCHASE_VALUE", start, end),
            "All New Purchase Value":       sum_col(df_shopify, "NEW_PURCHASE_VALUE", start, end),
            "Total Coffee Purchase Value":  sum_col(df_shopify, "COFFEE_PURCHASE_VALUE", start, end),
            "All Revenue":                  sum_col(df_shopify, "ALL_REVENUE", start, end),
        })

    rev_metrics = ["Meta Purchase Value", "All New Purchase Value",
                   "Total Coffee Purchase Value", "All Revenue"]
    rev_table_rows = []
    for m in rev_metrics:
        row = {"Metric": m}
        for r in rev_rows:
            row[r["period"]] = r[m]
        rev_table_rows.append(row)
    df_rev = pd.DataFrame(rev_table_rows)
    render_beige_table(df_rev, selected_col_name=selected_label)

    # ─── ROAS · CR · AOV ─────────────────────────────────────────────────────
    st.markdown('<div class="section-hdr">🎯 ROAS · CR · AOV</div>',
                 unsafe_allow_html=True)

    df_shopify_orders = run_query(f"""
        WITH first_orders AS (
            SELECT ORDER_ID,
                ROW_NUMBER() OVER (PARTITION BY EMAIL ORDER BY ORDER_TIMESTAMP, ORDER_ID) AS RN
            FROM (
                SELECT DISTINCT ORDER_ID, EMAIL, ORDER_TIMESTAMP
                FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUK_ALL_ORDERS_ITEMS
                WHERE ORDER_STATUS != 'CANCELLED'
            )
        )
        SELECT
            DATE(o.ORDER_TIMESTAMP) AS DATE_START,
            COUNT(DISTINCT o.ORDER_ID) AS TOTAL_ORDERS,
            COUNT(DISTINCT CASE WHEN fo.RN = 1 THEN o.ORDER_ID END) AS NEW_ORDERS,
            COUNT(DISTINCT CASE WHEN o.TAGS IS NULL OR o.TAGS NOT ILIKE '%Billing cycle%' THEN o.ORDER_ID END) AS NON_SUB_ORDERS,
            SUM(o.NET_SALES_BEFORE_TAX) AS TOTAL_SALES
        FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUK_ALL_ORDERS_ITEMS o
        LEFT JOIN first_orders fo ON o.ORDER_ID = fo.ORDER_ID
        WHERE o.ORDER_STATUS != 'CANCELLED'
          AND DATE(o.ORDER_TIMESTAMP) >= '{month_minus3_start_q}'
          AND DATE(o.ORDER_TIMESTAMP) <= '{yesterday}'
        GROUP BY DATE(o.ORDER_TIMESTAMP)
    """)

    df_new_plus_purchase = run_query(f"""
        WITH order_tags AS (
            SELECT
                DATE(ORDER_TIMESTAMP) AS DATE_START,
                ORDER_ID,
                SUM(NET_SALES_BEFORE_TAX) AS ORDER_REVENUE
            FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUK_ALL_ORDERS_ITEMS
            WHERE ORDER_STATUS != 'CANCELLED'
              AND DATE(ORDER_TIMESTAMP) >= '{month_minus3_start_q}'
              AND DATE(ORDER_TIMESTAMP) <= '{yesterday}'
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
    """)
    df_new_plus_purchase["DATE_START"] = pd.to_datetime(df_new_plus_purchase["DATE_START"]).dt.date
    df_shopify_orders["DATE_START"]    = pd.to_datetime(df_shopify_orders["DATE_START"]).dt.date

    df_sub_retention = run_query(f"""
        SELECT DATE(ORDER_TIMESTAMP) AS DATE_START,
            SUM(NET_SALES_BEFORE_TAX) AS SUB_RETENTION_REVENUE
        FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUK_ALL_ORDERS_ITEMS
        WHERE ORDER_STATUS != 'CANCELLED'
          AND TAGS ILIKE '%Billing Cycle%'
          AND TAGS NOT ILIKE '%Billing cycle #1%'
          AND DATE(ORDER_TIMESTAMP) >= '{month_minus3_start_q}'
          AND DATE(ORDER_TIMESTAMP) <= '{yesterday}'
        GROUP BY DATE(ORDER_TIMESTAMP)
    """)
    df_sub_retention["DATE_START"] = pd.to_datetime(df_sub_retention["DATE_START"]).dt.date

    def roas_metrics(period_name, start, end):
        total_ad_spent = sum_spend(df_raw, start, end)
        new_pv         = sum_col(df_shopify, "NEW_PURCHASE_VALUE", start, end)
        meta_pv        = sum_col(df_meta_pv, "META_PURCHASE_VALUE", start, end)
        all_revenue    = sum_col(df_shopify, "ALL_REVENUE", start, end)
        coffee_pv      = sum_col(df_shopify, "COFFEE_PURCHASE_VALUE", start, end)
        sub_ret        = sum_col(df_sub_retention, "SUB_RETENTION_REVENUE", start, end)
        new_plus_rev   = sum_col(df_new_plus_purchase, "NEW_PLUS_REVENUE", start, end)

        mask           = (df_shopify_orders["DATE_START"] >= start) & (df_shopify_orders["DATE_START"] <= end)
        subset         = df_shopify_orders.loc[mask]
        total_orders   = subset["TOTAL_ORDERS"].sum()
        new_orders     = subset["NEW_ORDERS"].sum()
        non_sub_orders = subset["NON_SUB_ORDERS"].sum()
        total_sales    = subset["TOTAL_SALES"].sum()

        mask_lpv = (df_meta["DATE_START"] >= start) & (df_meta["DATE_START"] <= end)
        lpv_total = df_meta.loc[mask_lpv, "LANDING_PAGE_VIEWS"].sum()

        new_purchase_roas       = round(new_pv / total_ad_spent, 2) if total_ad_spent > 0 else 0
        new_plus_purchase_roas  = round(new_plus_rev / total_ad_spent, 2) if total_ad_spent > 0 else 0
        meta_roas               = round(meta_pv / total_ad_spent, 2) if total_ad_spent > 0 else 0
        aov                     = round(total_sales / total_orders, 2) if total_orders > 0 else 0
        new_aov                 = round(new_pv / new_orders, 2) if new_orders > 0 else 0
        cr                      = round((non_sub_orders / lpv_total * 100), 2) if lpv_total > 0 else 0
        blended_roas            = round(all_revenue / total_ad_spent, 2) if total_ad_spent > 0 else 0
        coffee_blended          = round(coffee_pv / total_ad_spent, 2) if total_ad_spent > 0 else 0

        return {
            "New Purchase ROAS":     new_purchase_roas,
            "NEW+ Purchase ROAS":    new_plus_purchase_roas,
            "Just Meta ROAS":        meta_roas,
            "ROAS Wanted":           0.82,
            "AOV":                   aov,
            "New AOV":               new_aov,
            "CR":                    f"{cr}%",
            "Blended ROAS":          blended_roas,
            "Coffee Blended":        coffee_blended,
            "Sub Retention Revenue": sub_ret,
        }

    roas_metric_names = ["New Purchase ROAS", "NEW+ Purchase ROAS", "Just Meta ROAS",
                         "ROAS Wanted", "AOV", "New AOV", "CR", "Blended ROAS",
                         "Coffee Blended", "Sub Retention Revenue"]
    roas_period_data = {name: roas_metrics(name, start, end) for name, start, end in periods}
    roas_table_rows = []
    for m in roas_metric_names:
        row = {"Metric": m}
        for name, _, _ in periods:
            row[name] = roas_period_data[name][m]
        roas_table_rows.append(row)
    df_roas = pd.DataFrame(roas_table_rows)
    render_beige_table(df_roas, selected_col_name=selected_label)

    # ─── P&L ─────────────────────────────────────────────────────────────────
    st.markdown('<div class="section-hdr">📊 P&amp;L Statement '
                 '<span style="font-size:12px;color:#7a6a50;font-weight:500;">'
                 '— UK static COGS · FX 124 INR/GBP · Last Mile £3.50/order'
                 '</span></div>',
                 unsafe_allow_html=True)
    FX_RATE = 124.0
    LAST_MILE_PER_ORDER = 3.50

    df_cogs = run_query("""
        SELECT SKU, "COGS (INR)" AS COGS_INR, "Duty (GBP)" AS DUTY_GBP, "Outbound(GBP)" AS OUTBOUND_GBP
        FROM VAHDAM_DB.DASHBOARD_TABLES.APRIL_COGS
    """)

    df_orders_pnl = run_query(f"""
        SELECT
            DATE(ORDER_TIMESTAMP) AS DATE_START,
            SKU,
            SUM(NET_SALES_BEFORE_TAX) AS LINE_REVENUE,
            SUM(QUANTITY) AS LINE_QTY,
            COUNT(DISTINCT ORDER_ID) AS LINE_ORDERS
        FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUK_ALL_ORDERS_ITEMS
        WHERE ORDER_STATUS != 'CANCELLED'
          AND DATE(ORDER_TIMESTAMP) >= '{month_minus3_start_q}'
          AND DATE(ORDER_TIMESTAMP) <= '{yesterday}'
        GROUP BY DATE(ORDER_TIMESTAMP), SKU
    """)
    df_orders_pnl["DATE_START"] = pd.to_datetime(df_orders_pnl["DATE_START"]).dt.date
    df_orders_pnl = df_orders_pnl.merge(df_cogs, on="SKU", how="left")
    df_orders_pnl["COGS_INR"]     = df_orders_pnl["COGS_INR"].fillna(0)
    df_orders_pnl["DUTY_GBP"]     = df_orders_pnl["DUTY_GBP"].fillna(0)
    df_orders_pnl["OUTBOUND_GBP"] = df_orders_pnl["OUTBOUND_GBP"].fillna(0)

    df_orders_pnl["IS_COFFEE"] = df_orders_pnl["SKU"].str.contains("COFFEE", case=False, na=False)
    df_orders_pnl["NET_SALES_AFTER_TAX"] = df_orders_pnl.apply(
        lambda r: r["LINE_REVENUE"] * 5 / 6 if r["IS_COFFEE"] else r["LINE_REVENUE"], axis=1)
    df_orders_pnl["COGS_GBP"]       = df_orders_pnl["COGS_INR"] / FX_RATE * df_orders_pnl["LINE_QTY"]
    df_orders_pnl["DUTY_TOTAL"]     = df_orders_pnl["DUTY_GBP"]     * df_orders_pnl["LINE_QTY"]
    df_orders_pnl["OUTBOUND_TOTAL"] = df_orders_pnl["OUTBOUND_GBP"] * df_orders_pnl["LINE_QTY"]

    df_order_counts = run_query(f"""
        SELECT DATE(ORDER_TIMESTAMP) AS DATE_START, COUNT(DISTINCT ORDER_ID) AS TOTAL_ORDERS
        FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUK_ALL_ORDERS_ITEMS
        WHERE ORDER_STATUS != 'CANCELLED'
          AND DATE(ORDER_TIMESTAMP) >= '{month_minus3_start_q}'
          AND DATE(ORDER_TIMESTAMP) <= '{yesterday}'
        GROUP BY DATE(ORDER_TIMESTAMP)
    """)
    df_order_counts["DATE_START"] = pd.to_datetime(df_order_counts["DATE_START"]).dt.date

    df_pg_fees = run_query(f"""
        SELECT DATE(t.CREATED_AT) AS DATE_START,
            SUM(t.AMOUNT) AS TOTAL_PG_FEES
        FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUK_TRANSACTIONS t
        WHERE t.KIND = 'SALE' AND t.STATUS = 'SUCCESS'
          AND DATE(t.CREATED_AT) >= '{month_minus3_start_q}'
          AND DATE(t.CREATED_AT) <= '{yesterday}'
        GROUP BY DATE(t.CREATED_AT)
    """)
    df_pg_fees["DATE_START"] = pd.to_datetime(df_pg_fees["DATE_START"]).dt.date

    def pnl_metrics(start, end):
        mask = (df_orders_pnl["DATE_START"] >= start) & (df_orders_pnl["DATE_START"] <= end)
        subset = df_orders_pnl.loc[mask]
        net_sales     = round(subset["NET_SALES_AFTER_TAX"].sum(), 2)
        cogs          = round(subset["COGS_GBP"].sum(), 2)
        cogs_pct      = round((cogs / net_sales * 100), 2) if net_sales > 0 else 0
        duty          = round(subset["DUTY_TOTAL"].sum(), 2)
        duty_pct      = round((duty / net_sales * 100), 2) if net_sales > 0 else 0
        gross_margin  = round(net_sales - cogs - duty, 2)
        outbound      = round(subset["OUTBOUND_TOTAL"].sum(), 2)
        mask_pg       = (df_pg_fees["DATE_START"] >= start) & (df_pg_fees["DATE_START"] <= end)
        pg_commission = round(df_pg_fees.loc[mask_pg, "TOTAL_PG_FEES"].sum(), 2)
        pg_pct        = round((pg_commission / net_sales * 100), 2) if net_sales > 0 else 0
        shopify_costs = 0
        mask_oc       = (df_order_counts["DATE_START"] >= start) & (df_order_counts["DATE_START"] <= end)
        total_orders  = df_order_counts.loc[mask_oc, "TOTAL_ORDERS"].sum()
        last_mile     = round(total_orders * LAST_MILE_PER_ORDER, 2)
        storage       = 0
        cm1 = round(net_sales - cogs - duty - pg_commission - outbound - last_mile - storage, 2)
        total_ad_spent    = sum_spend(df_raw, start, end)
        agency_fees       = 1
        software_platform = 1
        cm2 = round(cm1 - total_ad_spent - agency_fees - software_platform, 2)
        supply_pct = round(((cogs + duty + outbound + last_mile + storage) / net_sales * 100), 2) if net_sales > 0 else 0
        return {
            "Net Sales (After Tax)":         net_sales,
            "COGS":                          cogs,
            "COGS %":                        f"{cogs_pct}%",
            "Duty (Ad Duty)":                duty,
            "Ad Duty %":                     f"{duty_pct}%",
            "Gross Margin":                  gross_margin,
            "Outbound":                      outbound,
            "PG Commission":                 pg_commission,
            "PG Commission %":               f"{pg_pct}%",
            "Shopify Costs":                 shopify_costs,
            "Last Mile (£3.50/order)":       last_mile,
            "Storage":                       storage,
            "Supply %":                      f"{supply_pct}%",
            "CM1":                           cm1,
            "Performance Marketing Cost":    total_ad_spent,
            "Agency Fees":                   agency_fees,
            "Software & Platform Cost":      software_platform,
            "CM2":                           cm2,
        }

    pnl_metric_names = ["Net Sales (After Tax)", "COGS", "COGS %", "Duty (Ad Duty)",
                        "Ad Duty %", "Gross Margin", "Outbound", "PG Commission",
                        "PG Commission %", "Shopify Costs", "Last Mile (£3.50/order)",
                        "Storage", "Supply %", "CM1", "Performance Marketing Cost",
                        "Agency Fees", "Software & Platform Cost", "CM2"]
    pnl_period_data = {name: pnl_metrics(start, end) for name, start, end in periods}
    pnl_table_rows = []
    for m in pnl_metric_names:
        row = {"Metric": m}
        for name, _, _ in periods:
            row[name] = pnl_period_data[name][m]
        pnl_table_rows.append(row)
    df_pnl = pd.DataFrame(pnl_table_rows)
    render_beige_table(df_pnl, selected_col_name=selected_label)

    # ─── COHORT LTV + SUBSCRIPTION RETENTION ─────────────────────────────────
    st.markdown('<div class="section-hdr" style="margin-top:24px;">'
                 'Cohort LTV &amp; Subscription Retention'
                 '</div>', unsafe_allow_html=True)

    _c1, _c2 = st.columns(2)
    with _c1:
        cohort_from = st.date_input("Cohort window — From",
                                     value=yesterday - timedelta(days=29),
                                     key="d2c_cohort_from")
    with _c2:
        cohort_to = st.date_input("Cohort window — To",
                                   value=yesterday,
                                   key="d2c_cohort_to")
    if cohort_from > cohort_to:
        st.error("'From' date must be on or before 'To'.")
        st.stop()

    st.markdown('<div class="section-hdr">Cohort LTV '
                 '<span style="font-size:12px;color:#7a6a50;font-weight:500;">'
                 '— customers acquired in picker window</span></div>',
                 unsafe_allow_html=True)
    st.caption(
        "Customer = unique email (lowercased). "
        "Net revenue = order total − refunds. "
        "Subscription renewals naturally compound into LTV."
    )

    df_cohort_raw = run_query(f"""
        WITH cohort_customers AS (
            SELECT
                LOWER(TRIM(EMAIL))           AS EMAIL,
                MIN(DATE(ORDER_TIMESTAMP))   AS FIRST_ORDER_DATE
            FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUK_ALL_ORDERS_ITEMS
            WHERE ORDER_STATUS != 'CANCELLED'
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
            ROUND(SUM(o.NET_SALES_BEFORE_TAX), 2)     AS REVENUE
        FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUK_ALL_ORDERS_ITEMS o
        JOIN cohort_customers c ON LOWER(TRIM(o.EMAIL)) = c.EMAIL
        WHERE o.ORDER_STATUS != 'CANCELLED'
        GROUP BY MONTH_NUM
        ORDER BY MONTH_NUM
    """)

    if df_cohort_raw.empty:
        st.info("No customers acquired in the selected window.")
    else:
        cohort_size        = int(df_cohort_raw.loc[df_cohort_raw["MONTH_NUM"] == 0,
                                                    "ACTIVE_CUSTOMERS"].sum())
        cumulative_revenue = round(float(df_cohort_raw["REVENUE"].sum()), 2)
        ltv_per_customer   = round(cumulative_revenue / cohort_size, 2) if cohort_size else 0.0

        # Cohort headline cards — Amazon-style `.pnl-strip` so they
        # match the rest of the dashboard's KPI look. Inline HTML
        # because the helper lives in app.py and we don't want a
        # circular import; the class itself is already loaded by the
        # main app's CSS.
        def _strip(label, value, sub=None):
            sub_html = (f'<div class="pnl-strip-sub">{sub}</div>'
                        if sub else "")
            return (f'<div class="pnl-strip">'
                    f'<div class="pnl-strip-label">{label}</div>'
                    f'<div class="pnl-strip-val">{value}</div>'
                    f'{sub_html}</div>')

        _k1, _k2, _k3 = st.columns(3, gap="small")
        _k1.markdown(_strip("Cohort size",
                             f"{cohort_size:,}",
                             "unique customers (by email)"),
                      unsafe_allow_html=True)
        _k2.markdown(_strip("Cumulative revenue",
                             f"£{cumulative_revenue:,.0f}",
                             f"over the cohort lifetime"),
                      unsafe_allow_html=True)
        _k3.markdown(_strip("LTV per customer",
                             f"£{ltv_per_customer:,.2f}",
                             "cumulative · per acquired customer"),
                      unsafe_allow_html=True)
        st.markdown("")

        _cum_rev  = 0.0
        _ltv_rows = []
        for _, _r in df_cohort_raw.iterrows():
            _m   = int(_r["MONTH_NUM"])
            _rev = round(float(_r["REVENUE"]), 2)
            _cum_rev += _rev
            _act = int(_r["ACTIVE_CUSTOMERS"])
            _ret = round(_act / cohort_size * 100, 2) if cohort_size else 0.0
            _cltv = round(_cum_rev / cohort_size, 2) if cohort_size else 0.0
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
        "<b>Net revenue</b> = order total − refunds. &nbsp;"
        "<b>Subscription renewals</b> naturally compound into LTV (they are regular Shopify orders). &nbsp;"
        "Move the picker above to recompute the cohort."
        "</small>",
        unsafe_allow_html=True,
    )

    # ─── SUBSCRIPTION RETENTION ──────────────────────────────────────────────
    st.markdown('<div class="section-hdr">Subscription Retention '
                 '<span style="font-size:12px;color:#7a6a50;font-weight:500;">'
                 '— Mₙ rate · 30-day plans · GBP · picker window</span></div>',
                 unsafe_allow_html=True)
    st.caption(
        f"Window: {cohort_from.strftime('%b %d, %Y')} → {cohort_to.strftime('%b %d, %Y')} · "
        "30-day plans only · source: Loop subscription contracts"
    )

    _RET_MAX = 8
    _sub_lookback = cohort_from - timedelta(days=_RET_MAX * 30)

    df_sub_starts = run_query(f"""
        SELECT
            DATE(ORDER_TIMESTAMP)     AS START_DATE,
            COUNT(DISTINCT ORDER_ID)  AS SUB_COUNT
        FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUK_ALL_ORDERS_ITEMS
        WHERE ORDER_STATUS != 'CANCELLED'
          AND TAGS ILIKE '%Billing cycle #1%'
          AND (TAGS ILIKE '%30 day%' OR TAGS ILIKE '%30-day%' OR TAGS ILIKE '%monthly%')
          AND DATE(ORDER_TIMESTAMP) >= '{_sub_lookback}'
          AND DATE(ORDER_TIMESTAMP) <= '{cohort_to}'
        GROUP BY DATE(ORDER_TIMESTAMP)
    """)
    df_sub_starts["START_DATE"] = pd.to_datetime(df_sub_starts["START_DATE"]).dt.date

    df_renewals = run_query(f"""
        SELECT
            REGEXP_SUBSTR(TAGS, 'Billing Cycle #([0-9]+)', 1, 1, 'ie', 1)::INT  AS CYCLE_NUM,
            COUNT(DISTINCT ORDER_ID)                                             AS VOL_Y,
            ROUND(SUM(NET_SALES_BEFORE_TAX), 2)                                 AS VOL_REVENUE
        FROM VAHDAM_DB.MAPLEMONK.SHOPIFYUK_ALL_ORDERS_ITEMS
        WHERE ORDER_STATUS != 'CANCELLED'
          AND TAGS ILIKE '%Billing cycle%'
          AND TAGS NOT ILIKE '%Billing cycle #1%'
          AND (TAGS ILIKE '%30 day%' OR TAGS ILIKE '%30-day%' OR TAGS ILIKE '%monthly%')
          AND DATE(ORDER_TIMESTAMP) >= '{cohort_from}'
          AND DATE(ORDER_TIMESTAMP) <= '{cohort_to}'
        GROUP BY CYCLE_NUM
        ORDER BY CYCLE_NUM
    """)

    _ret_rows = []
    for _n in range(1, _RET_MAX + 1):
        _cw_start = cohort_from - timedelta(days=_n * 30)
        _cw_end   = cohort_to   - timedelta(days=_n * 30)
        _mask_s   = (df_sub_starts["START_DATE"] >= _cw_start) & (df_sub_starts["START_DATE"] <= _cw_end)
        _cohort_x = int(df_sub_starts.loc[_mask_s, "SUB_COUNT"].sum())
        _cycle    = _n + 1
        _row_r    = df_renewals[df_renewals["CYCLE_NUM"] == _cycle]
        _vol_y    = int(_row_r["VOL_Y"].sum())
        _vol_rev  = round(float(_row_r["VOL_REVENUE"].sum()), 2)
        _vol_pct  = round(_vol_y / _cohort_x * 100, 2) if _cohort_x else 0.0
        _ret_rows.append({
            "Mₙ":                       f"M{_n}",
            "Subscriptions started in": f"{_cw_start.strftime('%b %d, %Y')} → {_cw_end.strftime('%b %d, %Y')}",
            "Cohort (X)":               _cohort_x,
            "Vol (Y')":                 _vol_y,
            "Vol %":                    f"{_vol_pct:.2f}%",
            "Vol revenue":              f"£{_vol_rev:,.2f}",
        })

    st.dataframe(pd.DataFrame(_ret_rows), use_container_width=True, hide_index=True)
    st.markdown(
        "<small>"
        "<b>Cohort (X)</b> = number of 30-day-plan subscriptions whose start date is exactly "
        "n × 30 days before the picker window [from, to]. &nbsp;"
        "<b>Volume (Y′)</b> = number of n-th recurring orders from any 30-day-plan subscription "
        "whose billing date landed inside [from, to] — regardless of which cohort the sub originally "
        "belonged to. Wider numerator absorbs billing-day variance, paused-then-resumed subs, and "
        "off-day starts. &nbsp;"
        "<b>Vol %</b> = Y′ ÷ X. &nbsp;"
        "<b>Vol revenue</b> = sum of NET_SALES_BEFORE_TAX across those n-th recurring orders."
        "</small>",
        unsafe_allow_html=True,
    )
