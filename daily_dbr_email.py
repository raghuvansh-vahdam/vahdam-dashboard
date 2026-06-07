"""
Daily DBR Email — Teas & Botanicals
====================================
Sends a beige-themed HTML business report at 15:30 IST each day,
mirroring the dashboard's Executive Summary KPI cards plus a
per-GEO breakdown so a CBO can absorb the whole picture in one
glance.

Invoked from .github/workflows/daily-dbr.yml on cron `0 10 * * *`
(10:00 UTC = 15:30 IST, just after the Maplemonk warehouse 3 PM
refresh).

Required env vars (set as GitHub Secrets — see DAILY_DBR_SETUP.md)
------------------------------------------------------------------
SNOWFLAKE_ACCOUNT     SNOWFLAKE_USER          SNOWFLAKE_PASSWORD
SNOWFLAKE_WAREHOUSE   SNOWFLAKE_ROLE
SNOWFLAKE_DATABASE    SNOWFLAKE_SCHEMA
DBR_GMAIL_USER        e.g. dashboard@vahdam.com — the FROM address
DBR_GMAIL_APP_PASSWORD 16-char Google App Password (NOT account pwd)
DBR_RECIPIENTS        comma-separated email list

Optional
--------
DBR_DRY_RUN=1   → prints the email HTML to stdout instead of sending.
                  Useful for local testing without burning a real send.
DBR_FORCE_YEST  → override the "yesterday" date (format YYYY-MM-DD).
                  Use when the IST 3 PM cutoff lands on a day whose
                  data is still loading (e.g. early-morning sends, or
                  a partial-load weekend day). The script will use the
                  supplied date as yesterday and back-compute MTD /
                  L7D / LM / LY windows from it. Falls back to the
                  normal _eff_today_ist() cutoff when unset.

Scope notes
-----------
* Category filter mirrors the dashboard's `_is_core_cat`:
  CATEGORY name must contain both "tea" and "botan" (case-insensitive),
  so "Tea and Botanicals", "Teas & Botanicals" etc. all match while
  Coffee / Supplements stay out.
* Brand is intentionally NOT filtered. The DBR is a category-cut
  (Teas & Botanicals) so it includes every brand within that
  category — Vahdam, Handpick (HP - Teas), Handpick Spices
  (HP - Spices, which the upstream feed rolls into the
  Tea & Botanicals category), etc. This matches the dashboard's
  Category view with no Brand filter applied.
* Date windows use the dashboard's IST 3 PM cutoff
  (`_eff_today_ist`): before 3 PM IST, "yesterday" = D-2 (the
  freshest fully-loaded day); after 3 PM, "yesterday" = D-1. The
  job is scheduled for 15:30 IST so production runs always see D-1,
  but local previews before the cutoff still match the dashboard.
"""
from __future__ import annotations

import os
import sys
import smtplib
import logging
from datetime import date, datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List, Optional, Tuple

import snowflake.connector
from dateutil.relativedelta import relativedelta


# ─── Config ─────────────────────────────────────────────────────────────
PNL_TABLE = "vahdam_db.maplemonk.vahdam_amazon_pnl_overall_fy27_onwards"
DASHBOARD_URL = "https://vahdam-dashboard.streamlit.app/"

# Five GEO buckets the email rolls up to. Order here = display order.
GEO_BUCKETS: List[str] = ["USA", "UK", "CA", "ROE", "AUS+UAE"]

# Friendly subject prefix
SUBJECT_PREFIX = "Vahdam Daily DBR — Teas & Botanicals"


# ─── Logging (stdout → GitHub Actions log) ──────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("dbr-email")


# ─── Snowflake connection ───────────────────────────────────────────────
def get_conn():
    return snowflake.connector.connect(
        account   = os.environ["SNOWFLAKE_ACCOUNT"],
        user      = os.environ["SNOWFLAKE_USER"],
        password  = os.environ["SNOWFLAKE_PASSWORD"],
        warehouse = os.environ["SNOWFLAKE_WAREHOUSE"],
        role      = os.environ["SNOWFLAKE_ROLE"],
        database  = os.environ["SNOWFLAKE_DATABASE"],
        schema    = os.environ["SNOWFLAKE_SCHEMA"],
        client_session_keep_alive=True,
        login_timeout=30,
        network_timeout=60,
    )


def run_query(conn, sql: str) -> List[Dict[str, object]]:
    """Run SELECT, return list of dict rows keyed by column name."""
    with conn.cursor(snowflake.connector.DictCursor) as cur:
        cur.execute(sql)
        return cur.fetchall()


# ─── Date windows — IST 3 PM cutoff (matches dashboard's _eff_today_ist)
IST = timezone(timedelta(hours=5, minutes=30))


def _eff_today_ist() -> date:
    """The freshest fully-loaded day in Snowflake.
    Before 15:00 IST → D-2 (day before yesterday)
    After  15:00 IST → D-1 (real yesterday)
    Mirrors the dashboard's per-geo `_eff_today_ist(geo=None)` default."""
    now_ist = datetime.now(IST)
    if now_ist.hour >= 15:
        return now_ist.date() - timedelta(days=1)
    return now_ist.date() - timedelta(days=2)


def compute_windows() -> Dict[str, Tuple[date, date]]:
    """Return the 9 date windows we'll query: 3 windows × (cur, LM, LY).
    DBR_FORCE_YEST env var (YYYY-MM-DD) overrides the IST cutoff —
    used when upstream data for the cutoff's natural yesterday is
    still loading and the user wants to lock to an earlier day."""
    override = os.environ.get("DBR_FORCE_YEST", "").strip()
    if override:
        try:
            yest = datetime.strptime(override, "%Y-%m-%d").date()
            log.info("DBR_FORCE_YEST override active: yesterday = %s", yest)
        except ValueError:
            log.warning("DBR_FORCE_YEST=%r is not YYYY-MM-DD — ignoring.",
                         override)
            yest = _eff_today_ist()
    else:
        yest = _eff_today_ist()
    mtd_start = yest.replace(day=1)
    mtd_end   = yest
    l7d_start = yest - timedelta(days=6)
    l7d_end   = yest

    def shift_m(d: date) -> date: return d - relativedelta(months=1)
    def shift_y(d: date) -> date: return d - relativedelta(years=1)

    return {
        "mtd":     (mtd_start,          mtd_end),
        "mtd_lm":  (shift_m(mtd_start), shift_m(mtd_end)),
        "mtd_ly":  (shift_y(mtd_start), shift_y(mtd_end)),
        "yest":    (yest,               yest),
        "yest_lm": (shift_m(yest),      shift_m(yest)),
        "yest_ly": (shift_y(yest),      shift_y(yest)),
        "l7d":     (l7d_start,          l7d_end),
        "l7d_lm":  (shift_m(l7d_start), shift_m(l7d_end)),
        "l7d_ly":  (shift_y(l7d_start), shift_y(l7d_end)),
    }


# ─── Per-window query ───────────────────────────────────────────────────
# All 6 underlying P&L metrics in one shot. Computed % metrics
# (CM1%, ACoS%, CM2%) are derived in Python from the raw sums so we
# can roll up to TOTAL using the proper weighted-average semantics
# (sum(num) / sum(den) — not avg of per-geo %s).
#
# GOOGLE_SPEND_ACTUAL_INR is included in the spend metric to mirror
# the dashboard's redefined ACoS = (PM Spend + GADS Spend) / Sales.
_QUERY = """
SELECT
    CASE
        WHEN GEO = 'USA' THEN 'USA'
        WHEN GEO = 'UK'  THEN 'UK'
        WHEN GEO = 'CA'  THEN 'CA'
        WHEN GEO IN ('DE','FR','IT','ES') THEN 'ROE'
        WHEN GEO IN ('AUS','UAE') THEN 'AUS+UAE'
        ELSE 'OTHER'
    END AS GEO_BUCKET,
    COALESCE(SUM(SALES_ACTUAL_INR), 0)        AS SALES_ACT,
    COALESCE(SUM(SALES_BUDGET_INR), 0)        AS SALES_BUD,
    COALESCE(SUM(QTY_ACTUAL), 0)              AS QTY_ACT,
    COALESCE(SUM(QTY_BUDGET), 0)              AS QTY_BUD,
    COALESCE(SUM(CM1_ACTUAL_INR), 0)          AS CM1_ACT,
    COALESCE(SUM(CM1_BUDGET_INR), 0)          AS CM1_BUD,
    COALESCE(SUM(CM2_ACTUAL_INR), 0)          AS CM2_ACT,
    COALESCE(SUM(CM2_BUDGET_INR), 0)          AS CM2_BUD,
    (COALESCE(SUM(PM_SPEND_ACTUAL_INR), 0)
     + COALESCE(SUM(GOOGLE_SPEND_ACTUAL_INR), 0)) AS SPEND_ACT,
    COALESCE(SUM(PM_SPEND_BUDGET_INR), 0)     AS SPEND_BUD
FROM {table}
WHERE DAY BETWEEN '{d1}' AND '{d2}'
  AND GEO NOT IN ('IN', 'MX')
  AND LOWER(COALESCE(CATEGORY, '')) LIKE '%tea%'
  AND LOWER(COALESCE(CATEGORY, '')) LIKE '%botan%'
GROUP BY GEO_BUCKET
"""
# Note: no Brand / AMZ_CATEGORY exclusion. The DBR is a category-cut
# (Teas & Botanicals) which rolls in every brand tagged under that
# category in the FY27 P&L feed — including HP - Teas and HP - Spices.
# Matches the dashboard's Category view with no Brand filter.

# Keys we carry per geo bucket
_METRICS = ("SALES_ACT", "SALES_BUD", "QTY_ACT", "QTY_BUD",
            "CM1_ACT", "CM1_BUD", "CM2_ACT", "CM2_BUD",
            "SPEND_ACT", "SPEND_BUD")

WindowData = Dict[str, Dict[str, float]]   # geo → {metric: value}


def _zero_row() -> Dict[str, float]:
    return {k: 0.0 for k in _METRICS}


def fetch_window(conn, d_from: date, d_to: date) -> WindowData:
    """Return {geo_bucket: {metric: value}} for a date window."""
    sql = _QUERY.format(table=PNL_TABLE, d1=d_from, d2=d_to)
    rows = run_query(conn, sql)
    by_geo: WindowData = {g: _zero_row() for g in GEO_BUCKETS}
    for r in rows:
        g = r["GEO_BUCKET"]
        if g not in by_geo:
            continue
        for k in _METRICS:
            by_geo[g][k] = float(r[k] or 0)
    return by_geo


def totals_row(by_geo: WindowData) -> Dict[str, float]:
    """Sum all metrics across the 5 GEO buckets."""
    t = _zero_row()
    for g in by_geo.values():
        for k in _METRICS:
            t[k] += g[k]
    return t


# ─── Number formatting ──────────────────────────────────────────────────
def fmt_inr(v: Optional[float]) -> str:
    """₹ in Cr / L / K with one or two decimal places."""
    if v is None: return "—"
    v = float(v)
    sign = "-" if v < 0 else ""
    a = abs(v)
    if a >= 1e7:   return f"{sign}₹{a/1e7:,.2f}Cr"
    if a >= 1e5:   return f"{sign}₹{a/1e5:,.2f}L"
    if a >= 1e3:   return f"{sign}₹{a/1e3:,.1f}K"
    return f"{sign}₹{a:,.0f}"


def fmt_units(v: Optional[float]) -> str:
    """Units in K / M short form, no currency symbol."""
    if v is None: return "—"
    v = float(v)
    sign = "-" if v < 0 else ""
    a = abs(v)
    if a >= 1e7:   return f"{sign}{a/1e7:,.2f}Cr"
    if a >= 1e5:   return f"{sign}{a/1e5:,.2f}L"
    if a >= 1e3:   return f"{sign}{a/1e3:,.1f}K"
    return f"{sign}{a:,.0f}"


def fmt_pct(v: Optional[float]) -> str:
    """Percentage value with one decimal (already in 0–100 scale)."""
    if v is None: return "—"
    return f"{v:.1f}%"


def fmt_ratio_pct(num: float, den: float) -> Optional[float]:
    """num/den × 100, returning None on zero denominator."""
    if den is None or den == 0:
        return None
    return num / den * 100


def fmt_growth_pct(cur: Optional[float], prev: Optional[float]) -> Optional[float]:
    """Relative growth in %, returning None when prev is 0/None."""
    if cur is None or prev is None or prev == 0:
        return None
    return (cur - prev) / abs(prev) * 100


def fmt_delta_html(cur: Optional[float], prev: Optional[float],
                   lower_better: bool = False) -> Tuple[str, str]:
    """Return (text_html, color) for a vs LM / vs LY cell.
    text_html: '▲ 5.6%' / '▼ 13.3%' / '—'
    color:     hex string"""
    if cur is None or prev is None or prev == 0:
        return ("—", "#7a6a50")
    pct = (cur - prev) / abs(prev) * 100
    is_up = pct >= 0
    arrow = "▲" if is_up else "▼"
    if lower_better:
        is_good = (not is_up)
    else:
        is_good = is_up
    if abs(pct) < 0.05:
        color = "#7a6a50"
    else:
        color = "#1a7a3e" if is_good else "#8b1a1a"
    return (f"{arrow} {abs(pct):.1f}%", color)


# ─── Per-metric configuration ───────────────────────────────────────────
# Each entry: (label, kind, lower_better)
#   kind = 'ccy'   → currency (₹ Cr/L/K). Bud + LM raw + LY raw shown
#                    as currency. % vs B = act/bud.
#   kind = 'units' → unit count. Same shape as ccy but no currency.
#   kind = 'pct'   → percentage metric. Bud + LM raw + LY raw shown
#                    as percentages. % vs B = (act / bud) but we
#                    display the actual value with vs-B pill colored.
#   lower_better: ACoS — when True, %-vs-B band reverses and LM/LY
#                 delta colours invert.
_METRIC_CARDS = [
    ("Revenue",  "ccy",   False),
    ("Quantity", "units", False),
    ("CM1%",     "pct",   False),
    ("ACoS%",    "pct",   True),
    ("CM2%",     "pct",   False),
    ("CM2 Abs",  "ccy",   False),
]


def metric_values(row: Dict[str, float], label: str
                  ) -> Tuple[Optional[float], Optional[float]]:
    """Return (actual, budget) for a given metric label, derived
    from the raw P&L sums in the row dict. % metrics divide by sales."""
    if label == "Revenue":
        return row["SALES_ACT"], row["SALES_BUD"]
    if label == "Quantity":
        return row["QTY_ACT"], row["QTY_BUD"]
    if label == "CM1%":
        return (fmt_ratio_pct(row["CM1_ACT"], row["SALES_ACT"]),
                fmt_ratio_pct(row["CM1_BUD"], row["SALES_BUD"]))
    if label == "ACoS%":
        return (fmt_ratio_pct(row["SPEND_ACT"], row["SALES_ACT"]),
                fmt_ratio_pct(row["SPEND_BUD"], row["SALES_BUD"]))
    if label == "CM2%":
        return (fmt_ratio_pct(row["CM2_ACT"], row["SALES_ACT"]),
                fmt_ratio_pct(row["CM2_BUD"], row["SALES_BUD"]))
    if label == "CM2 Abs":
        return row["CM2_ACT"], row["CM2_BUD"]
    return (None, None)


def _fmt_value(v: Optional[float], kind: str) -> str:
    if v is None: return "—"
    if kind == "ccy":   return fmt_inr(v)
    if kind == "units": return fmt_units(v)
    if kind == "pct":   return fmt_pct(v)
    return f"{v:,.2f}"


# ─── Cell colors ────────────────────────────────────────────────────────
def color_ach_pill(act: Optional[float], bud: Optional[float],
                   lower_better: bool) -> Tuple[str, str]:
    """Return (bg, fg) for the % vs B pill. Mirrors dashboard tiers."""
    if act is None or bud is None or bud == 0:
        return ("#EDE8DC", "#7a6a50")
    pct = act / bud * 100
    if lower_better:
        if pct <= 100:   return ("#d4ecd4", "#1a7a3e")
        if pct <= 110:   return ("#fde9c8", "#7a5c00")
        return ("#fdd8d8", "#8b1a1a")
    if pct >= 100:   return ("#d4ecd4", "#1a7a3e")
    if pct >=  90:   return ("#fde9c8", "#7a5c00")
    return ("#fdd8d8", "#8b1a1a")


# ─── KPI card renderer ──────────────────────────────────────────────────
def render_kpi_card(label: str, kind: str, lower_better: bool,
                    cur_row: Dict[str, float],
                    lm_row: Dict[str, float],
                    ly_row: Dict[str, float]) -> str:
    """One KPI card matching the dashboard's Exec Summary look.
    Top to bottom: label · big value · Bud line · vs-B pill · vs LM · vs LY.
    """
    cur_act, cur_bud = metric_values(cur_row, label)
    lm_act,  _       = metric_values(lm_row,  label)
    ly_act,  _       = metric_values(ly_row,  label)

    val_str = _fmt_value(cur_act, kind)
    bud_str = _fmt_value(cur_bud, kind)
    ach_pct = (cur_act / cur_bud * 100) if (cur_act is not None
                and cur_bud not in (None, 0)) else None
    ach_str = f"{ach_pct:.1f}%" if ach_pct is not None else "—"
    pill_bg, pill_fg = color_ach_pill(cur_act, cur_bud, lower_better)

    lm_html, lm_color = fmt_delta_html(cur_act, lm_act, lower_better)
    ly_html, ly_color = fmt_delta_html(cur_act, ly_act, lower_better)
    lm_raw_str = _fmt_value(lm_act, kind)
    ly_raw_str = _fmt_value(ly_act, kind)

    return f"""
    <td valign="top" style="padding:6px;">
      <div style="background:#FBF5EA;border:1px solid #d6ccba;
                  border-top:3px solid #AB8743;border-radius:10px;
                  padding:14px 12px;text-align:center;
                  min-width:155px;font-family:Helvetica,Arial,sans-serif;
                  box-shadow:0 2px 6px rgba(120,80,30,0.06);">
        <div style="font-size:10px;font-weight:700;letter-spacing:1.8px;
                    color:#AB8743;text-transform:uppercase;">{label}</div>
        <div style="font-size:22px;font-weight:700;color:#004A2B;
                    margin:6px 0 2px 0;">{val_str}</div>
        <div style="font-size:11px;color:#7a6a50;margin-bottom:8px;">
          Bud: {bud_str}</div>
        <div style="display:inline-block;background:{pill_bg};
                    color:{pill_fg};font-weight:700;font-size:11px;
                    padding:3px 10px;border-radius:12px;
                    margin-bottom:8px;">{ach_str} vs B</div>
        <div style="font-size:11px;font-weight:600;color:{lm_color};
                    margin-top:2px;">
          {lm_html} <span style="color:#7a6a50;font-weight:500;">
          vs LM ({lm_raw_str})</span></div>
        <div style="font-size:11px;font-weight:600;color:{ly_color};
                    margin-top:2px;">
          {ly_html} <span style="color:#7a6a50;font-weight:500;">
          vs LY ({ly_raw_str})</span></div>
      </div>
    </td>
    """


def render_kpi_row(label: str,
                   cur: WindowData, lm: WindowData, ly: WindowData) -> str:
    """The 6-card strip for a single window, computed from TOTAL all-geo."""
    cur_tot = totals_row(cur)
    lm_tot  = totals_row(lm)
    ly_tot  = totals_row(ly)
    cards   = "".join(
        render_kpi_card(lbl, kind, lb, cur_tot, lm_tot, ly_tot)
        for (lbl, kind, lb) in _METRIC_CARDS
    )
    return f"""
    <table cellpadding="0" cellspacing="0" border="0"
           style="border-collapse:separate;border-spacing:0;
                  margin:4px 0 18px 0;width:100%;">
      <tr>{cards}</tr>
    </table>
    """


# ─── Per-GEO breakdown table ────────────────────────────────────────────
_TABLE_CSS = (
    "width:100%;border-collapse:collapse;font-family:Helvetica,Arial,"
    "sans-serif;font-size:12px;color:#3e2f1c;border:1px solid #d6ccba;"
    "border-radius:8px;overflow:hidden;margin:6px 0 14px 0;"
)
_TH_CSS = (
    "background:linear-gradient(180deg,#004A2B 0%,#2E7D32 100%);"
    "color:#FBF5EA;padding:9px 8px;text-align:left;font-weight:700;"
    "letter-spacing:0.3px;font-size:10px;text-transform:uppercase;"
    "border-bottom:2px solid #AB8743;"
)
_TD_CSS = (
    "padding:8px;border-bottom:1px solid #ead9b5;"
    "color:#1a1a1a;vertical-align:middle;font-size:12px;"
)


def render_geo_table(cur: WindowData,
                     lm: WindowData,
                     ly: WindowData) -> str:
    """Per-GEO table — one row per bucket + a TOTAL row at the top.
    Columns: GEO · Revenue (Act/Bud/%vs B) · CM1% · ACoS% · CM2% · CM2 Abs."""

    def _row(label: str, row: Dict[str, float],
             row_lm: Dict[str, float], row_ly: Dict[str, float],
             *, is_total: bool = False) -> str:
        cells = []
        weight = "700" if is_total else "500"
        row_bg = "background-color:#EDE8DC;" if is_total else ""

        # First column — GEO label
        cells.append(
            f'<td style="{_TD_CSS}font-weight:{weight};color:#004A2B;'
            f'text-align:left;letter-spacing:0.3px;">{label}</td>'
        )

        # Revenue cell (3 lines: Actual / Bud / % vs B colored)
        sales_act, sales_bud = metric_values(row, "Revenue")
        ach = sales_act / sales_bud * 100 if (sales_bud and sales_bud > 0) else None
        pill_bg, pill_fg = color_ach_pill(sales_act, sales_bud, False)
        ach_str = f"{ach:.1f}%" if ach is not None else "—"
        cells.append(
            f'<td style="{_TD_CSS}text-align:right;">'
            f'<div style="font-weight:{weight};color:#171717;">{fmt_inr(sales_act)}</div>'
            f'<div style="font-size:10px;color:#7a6a50;">Bud {fmt_inr(sales_bud)}</div>'
            f'<div style="display:inline-block;background:{pill_bg};color:{pill_fg};'
            f'font-weight:700;font-size:10px;padding:1px 6px;border-radius:8px;'
            f'margin-top:3px;">{ach_str}</div>'
            f'</td>'
        )

        # Helper for the %-metric cells (CM1% / CM2% / ACoS%)
        def _pct_cell(metric_label: str, lower_better: bool) -> str:
            a, b = metric_values(row, metric_label)
            bg, fg = color_ach_pill(a, b, lower_better)
            a_str = fmt_pct(a)
            b_str = fmt_pct(b)
            return (
                f'<td style="{_TD_CSS}text-align:right;">'
                f'<div style="font-weight:{weight};color:{fg};">{a_str}</div>'
                f'<div style="font-size:10px;color:#7a6a50;">Bud {b_str}</div>'
                f'</td>'
            )

        cells.append(_pct_cell("CM1%",  False))
        cells.append(_pct_cell("ACoS%", True))
        cells.append(_pct_cell("CM2%",  False))

        # CM2 Abs cell
        cm2_act, cm2_bud = metric_values(row, "CM2 Abs")
        ach2 = cm2_act / cm2_bud * 100 if (cm2_bud and cm2_bud > 0) else None
        pill_bg2, pill_fg2 = color_ach_pill(cm2_act, cm2_bud, False)
        ach2_str = f"{ach2:.1f}%" if ach2 is not None else "—"
        cells.append(
            f'<td style="{_TD_CSS}text-align:right;">'
            f'<div style="font-weight:{weight};color:#171717;">{fmt_inr(cm2_act)}</div>'
            f'<div style="font-size:10px;color:#7a6a50;">Bud {fmt_inr(cm2_bud)}</div>'
            f'<div style="display:inline-block;background:{pill_bg2};color:{pill_fg2};'
            f'font-weight:700;font-size:10px;padding:1px 6px;border-radius:8px;'
            f'margin-top:3px;">{ach2_str}</div>'
            f'</td>'
        )

        return f'<tr style="{row_bg}">' + "".join(cells) + "</tr>"

    # Header
    header = (
        '<tr>'
        f'<th style="{_TH_CSS}text-align:left;">GEO</th>'
        f'<th style="{_TH_CSS}text-align:right;">Revenue</th>'
        f'<th style="{_TH_CSS}text-align:right;">CM1%</th>'
        f'<th style="{_TH_CSS}text-align:right;">ACoS%</th>'
        f'<th style="{_TH_CSS}text-align:right;">CM2%</th>'
        f'<th style="{_TH_CSS}text-align:right;">CM2 Abs</th>'
        '</tr>'
    )

    cur_tot = totals_row(cur)
    lm_tot  = totals_row(lm)
    ly_tot  = totals_row(ly)
    rows = [_row("TOTAL", cur_tot, lm_tot, ly_tot, is_total=True)]
    for g in GEO_BUCKETS:
        rows.append(_row(g, cur[g], lm[g], ly[g]))

    return (f'<table style="{_TABLE_CSS}">'
            + header + "".join(rows)
            + '</table>')


def render_window_block(title: str, subtitle: str,
                        cur: WindowData,
                        lm:  WindowData,
                        ly:  WindowData,
                        *, show_kpi_cards: bool = True) -> str:
    """A single window section: divider + (optional) KPI cards + per-GEO table.
    `show_kpi_cards` controls whether the 6-card hero strip renders. Only
    the MTD block uses cards — Yesterday and L7D use the per-GEO table
    only, since the cards on those windows mostly restate the table's
    TOTAL row and waste vertical real estate."""
    kpi_html = render_kpi_row(title, cur, lm, ly) if show_kpi_cards else ""
    breakdown_label = (
        '<div style="font-size:11px;font-weight:600;color:#5a4d35;'
        'margin:8px 0 4px 0;letter-spacing:0.3px;">'
        'Per-GEO breakdown</div>'
    ) if show_kpi_cards else ""
    return f"""
    <div style="margin:24px 0 4px 0;border-left:4px solid #AB8743;
                padding-left:12px;">
      <div style="font-size:15px;font-weight:700;color:#004A2B;
                  letter-spacing:0.5px;text-transform:uppercase;">{title}</div>
      <div style="font-size:11px;color:#7a6a50;margin-top:2px;">{subtitle}</div>
    </div>
    {kpi_html}
    {breakdown_label}
    {render_geo_table(cur, lm, ly)}
    """


# ─── Compose the full email ─────────────────────────────────────────────
def build_email_html(data: Dict[str, WindowData],
                     windows: Dict[str, Tuple[date, date]]) -> str:
    def fmt_range(d1: date, d2: date) -> str:
        if d1 == d2:
            return d1.strftime("%d %b %Y")
        return f"{d1.strftime('%d %b')} → {d2.strftime('%d %b %Y')}"

    snapshot_ist = datetime.now(IST).strftime("%d %b %Y · %H:%M IST")

    body_parts = [
        # Header banner
        f'<div style="font-size:20px;font-weight:700;color:#004A2B;'
        f'letter-spacing:0.5px;">VAHDAM · Daily Business Report</div>',
        f'<div style="font-size:13px;color:#7a6a50;margin-top:2px;">'
        f'Teas &amp; Botanicals · Snapshot {snapshot_ist} '
        f'&nbsp;·&nbsp; <a href="{DASHBOARD_URL}" '
        f'style="color:#004A2B;font-weight:600;text-decoration:none;'
        f'border-bottom:1px dotted #004A2B;">Open full dashboard →</a>'
        f'</div>',
    ]

    # Three window sections — MTD first (CBO's primary read), then
    # Yesterday (latest tick), then L7D (smoothed trend).
    body_parts.append(
        render_window_block(
            "Month-to-Date",
            f"{fmt_range(*windows['mtd'])} · same elapsed days "
            f"last month / last year",
            data["mtd"], data["mtd_lm"], data["mtd_ly"],
            show_kpi_cards=True)
    )
    body_parts.append(
        render_window_block(
            "Yesterday",
            f"{fmt_range(*windows['yest'])} · same calendar day "
            f"last month / last year",
            data["yest"], data["yest_lm"], data["yest_ly"],
            show_kpi_cards=False)
    )
    body_parts.append(
        render_window_block(
            "Last 7 Days",
            f"{fmt_range(*windows['l7d'])} · same 7-day window "
            f"last month / last year",
            data["l7d"], data["l7d_lm"], data["l7d_ly"],
            show_kpi_cards=False)
    )

    # Footer
    body_parts.append(
        '<div style="font-size:11px;color:#7a6a50;margin-top:24px;'
        'padding-top:14px;border-top:1px solid #d6ccba;line-height:1.6;">'
        '<b>Scope:</b> Teas &amp; Botanicals only (Coffee &amp; '
        'Supplements excluded). HP-prefixed AMZ categories '
        '(HP - Spices, HP - Teas …) are Handpick products and are '
        'excluded.<br>'
        '<b>GEO buckets:</b> ROE = DE + FR + IT + ES &middot; '
        'AUS+UAE = Australia + UAE.<br>'
        '<b>ACoS%</b> = (PM Spend + GADS Spend) / Sales. '
        '<b>vs LM</b> = same window shifted -1 calendar month. '
        '<b>vs LY</b> = same window shifted -1 calendar year.<br>'
        '<b>Data cutoff:</b> Maplemonk 3 PM IST refresh — yesterday '
        'is the freshest fully-loaded day at send time (15:30 IST).<br>'
        'Generated by the Vahdam dashboard repo · GitHub Actions cron.'
        '</div>'
    )

    inner = "\n".join(body_parts)

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>body{{margin:0;padding:0;background:#f5efe0;}}</style></head>
<body style="background:#f5efe0;padding:20px;font-family:Helvetica,
Arial,sans-serif;color:#3e2f1c;">
<div style="max-width:1040px;margin:0 auto;background:#FBF5EA;
padding:24px 28px;border-radius:14px;
box-shadow:0 4px 14px rgba(120,80,30,0.10);
border-top:5px solid #AB8743;">
{inner}
</div></body></html>"""


# ─── SMTP send ──────────────────────────────────────────────────────────
def send_email(html_body: str, subject: str,
               sender: str, password: str,
               recipients: List[str]) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = ", ".join(recipients)
    msg.attach(MIMEText(
        "This is the Vahdam Daily DBR. Your email client doesn't support HTML.\n"
        "Open in a modern client (Gmail / Outlook) to see the formatted report.",
        "plain"))
    msg.attach(MIMEText(html_body, "html"))

    log.info("Connecting to smtp.gmail.com:587 …")
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as srv:
        srv.starttls()
        srv.login(sender, password)
        srv.sendmail(sender, recipients, msg.as_string())
    log.info("Email sent to %d recipient(s).", len(recipients))


# ─── Main ───────────────────────────────────────────────────────────────
def main() -> int:
    dry_run = os.environ.get("DBR_DRY_RUN") == "1"

    recipients = [
        e.strip() for e in os.environ.get("DBR_RECIPIENTS", "").split(",")
        if e.strip()
    ]
    if not recipients and not dry_run:
        log.error("DBR_RECIPIENTS is empty — nothing to send.")
        return 1

    windows = compute_windows()
    log.info("Date windows: %s",
             {k: f"{v[0]} → {v[1]}" for k, v in windows.items()})

    log.info("Connecting to Snowflake …")
    conn = get_conn()
    try:
        log.info("Querying %d windows …", len(windows))
        data: Dict[str, WindowData] = {}
        for key, (d1, d2) in windows.items():
            log.info("  · %-8s %s → %s", key, d1, d2)
            data[key] = fetch_window(conn, d1, d2)
    finally:
        conn.close()

    # Visibility: print TOTAL Revenue per window so we can sanity-check
    # the numbers against the dashboard before sending.
    log.info("Totals (Revenue):")
    for k in ("mtd", "yest", "l7d"):
        t = totals_row(data[k])
        log.info("  · %-5s %s  vs Bud %s",
                 k, fmt_inr(t["SALES_ACT"]), fmt_inr(t["SALES_BUD"]))

    html_body = build_email_html(data, windows)
    yest_str  = windows["yest"][0].strftime("%d %b %Y")
    subject   = f"{SUBJECT_PREFIX} · {yest_str}"

    if dry_run:
        log.info("DBR_DRY_RUN=1 → printing HTML to stdout (not sending).")
        sys.stdout.write(html_body)
        sys.stdout.write("\n")
        return 0

    send_email(
        html_body=html_body,
        subject=subject,
        sender=os.environ["DBR_GMAIL_USER"],
        password=os.environ["DBR_GMAIL_APP_PASSWORD"],
        recipients=recipients,
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        log.exception("Daily DBR email failed.")
        sys.exit(2)
