"""
Daily DBR Email
===============
Sends a beige-themed HTML summary email at 3:30 PM IST each day with
Vahdam's Teas & Botanicals P&L vs Budget across three windows
(MTD / Yesterday / Last 7 Days) and five GEO buckets
(USA / UK / CA / ROE / AUS+UAE), plus % vs LM and % vs LY columns.

Invoked from .github/workflows/daily-dbr.yml on cron `0 10 * * *`
(10:00 UTC = 15:30 IST, just after the Maplemonk warehouse 3 PM
data refresh finishes).

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
DBR_DRY_RUN=1 → prints the email HTML to stdout instead of sending.
                Useful for local testing without burning a real send.

Scope notes
-----------
* Category filter mirrors the dashboard's `_is_core_cat`:
  CATEGORY name must contain both "tea" and "botan" (case-insensitive),
  so "Tea and Botanicals", "Teas & Botanicals" etc. all match while
  Coffee / Supplements stay out.
* HP-prefixed AMZ_CATEGORY rows (HP - Spices, HP - Teas …) are
  Handpick products in source data; we exclude them so the email
  represents Vahdam Teas only, mirroring the sidebar Brand=Vahdam
  filter rule.
* Date windows are anchored to IST yesterday (the freshest fully-
  loaded day at 3:30 PM IST). LM = same window shifted -1 calendar
  month; LY = same window shifted -1 calendar year, both via
  dateutil.relativedelta so month-end edge cases (e.g. Mar 31 -> Feb
  28) are handled cleanly.
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

# Five GEO buckets the email rolls up to. Order here = display order.
GEO_BUCKETS: List[str] = ["USA", "UK", "CA", "ROE", "AUS+UAE"]

# Friendly names for headlines (no markdown — this goes into the
# subject line / HTML title).
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
    """Open a Snowflake connection from env-var credentials.
    Same warehouse/role the Streamlit dashboard uses.
    """
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
    """Run a SELECT, return list of dict rows keyed by column name."""
    with conn.cursor(snowflake.connector.DictCursor) as cur:
        cur.execute(sql)
        return cur.fetchall()


# ─── Date windows ───────────────────────────────────────────────────────
IST = timezone(timedelta(hours=5, minutes=30))


def compute_windows() -> Dict[str, Tuple[date, date]]:
    """Return the 9 date windows (3 current + 3 LM + 3 LY) we'll query.

    Anchored to IST yesterday — the email runs at 3:30 PM IST, so all
    geos' upstream loads (3 PM USA/CA, 11 AM UK/EU/AUS/UAE) have
    completed. Yesterday is the freshest fully-loaded day.
    """
    now_ist = datetime.now(IST)
    yest = now_ist.date() - timedelta(days=1)

    mtd_start = yest.replace(day=1)
    mtd_end   = yest
    l7d_start = yest - timedelta(days=6)
    l7d_end   = yest

    # LM = shift one calendar month. relativedelta handles month-end
    # edge cases (e.g. Mar 31 -> Feb 28).
    def shift_m(d: date) -> date: return d - relativedelta(months=1)
    def shift_y(d: date) -> date: return d - relativedelta(years=1)

    return {
        "mtd":        (mtd_start,            mtd_end),
        "mtd_lm":     (shift_m(mtd_start),   shift_m(mtd_end)),
        "mtd_ly":     (shift_y(mtd_start),   shift_y(mtd_end)),
        "yest":       (yest,                 yest),
        "yest_lm":    (shift_m(yest),        shift_m(yest)),
        "yest_ly":    (shift_y(yest),        shift_y(yest)),
        "l7d":        (l7d_start,            l7d_end),
        "l7d_lm":     (shift_m(l7d_start),   shift_m(l7d_end)),
        "l7d_ly":     (shift_y(l7d_start),   shift_y(l7d_end)),
    }


# ─── Per-window query ───────────────────────────────────────────────────
# One query per window keeps the SQL readable and the per-call latency
# tiny. The dashboard's same brand exclusion rule is applied here so
# HP - Spices etc. stay out of the Vahdam Teas roll-up.
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
    ROUND(SUM(SALES_ACTUAL_INR), 0) AS ACT,
    ROUND(SUM(SALES_BUDGET_INR), 0) AS BUD
FROM {table}
WHERE DAY BETWEEN '{d1}' AND '{d2}'
  AND GEO NOT IN ('IN', 'MX')
  AND LOWER(COALESCE(CATEGORY, '')) LIKE '%tea%'
  AND LOWER(COALESCE(CATEGORY, '')) LIKE '%botan%'
  AND NOT (LOWER(TRIM(COALESCE(AMZ_CATEGORY, ''))) LIKE 'hp -%')
GROUP BY GEO_BUCKET
"""


def fetch_window(conn, d_from: date, d_to: date) -> Dict[str, Tuple[float, float]]:
    """Return {geo_bucket: (actual_inr, budget_inr)} for a date window.
    Buckets with no rows are returned as (0, 0) so the table always
    has 5 + TOTAL rows even when a geo had zero activity."""
    sql = _QUERY.format(table=PNL_TABLE, d1=d_from, d2=d_to)
    rows = run_query(conn, sql)

    by_geo: Dict[str, Tuple[float, float]] = {g: (0.0, 0.0) for g in GEO_BUCKETS}
    for r in rows:
        g = r["GEO_BUCKET"]
        if g in by_geo:
            by_geo[g] = (float(r["ACT"] or 0), float(r["BUD"] or 0))
    return by_geo


def totals_row(by_geo: Dict[str, Tuple[float, float]]) -> Tuple[float, float]:
    act = sum(v[0] for v in by_geo.values())
    bud = sum(v[1] for v in by_geo.values())
    return act, bud


# ─── Number formatting (Indian Lakhs / Crores) ──────────────────────────
def fmt_inr(v: Optional[float]) -> str:
    """₹ value in lakhs/crores with one decimal. Examples:
       8,97,00,000 → ₹8.97Cr
       45,80,000   → ₹45.8L
       8,400       → ₹8.4K
       0           → ₹0
    """
    if v is None: return "—"
    v = float(v)
    sign = "-" if v < 0 else ""
    a = abs(v)
    if a >= 1e7:   return f"{sign}₹{a/1e7:,.2f}Cr"
    if a >= 1e5:   return f"{sign}₹{a/1e5:,.2f}L"
    if a >= 1e3:   return f"{sign}₹{a/1e3:,.1f}K"
    return f"{sign}₹{a:,.0f}"


def fmt_pct(curr: Optional[float], base: Optional[float]) -> str:
    """Returns 'X%' for achievement or '—' if base is zero/None."""
    if curr is None or base is None or base == 0:
        return "—"
    return f"{curr / base * 100:.1f}%"


def fmt_delta_pct(curr: Optional[float], prior: Optional[float]) -> str:
    """Returns '+X.X%' / '-X.X%' or '—' for LM / LY growth."""
    if curr is None or prior is None or prior == 0:
        return "—"
    pct = (curr - prior) / abs(prior) * 100
    return f"{pct:+.1f}%"


# ─── Cell coloring rules ────────────────────────────────────────────────
def color_ach(curr: Optional[float], base: Optional[float]) -> str:
    """Background color for %-vs-Budget cell. Mirrors dashboard tiers:
    >=100% green, 90-99 amber, <90 red. Empty / NaN → neutral beige."""
    if curr is None or base is None or base == 0:
        return "#f4eed8"
    pct = curr / base * 100
    if pct >= 100: return "#d4ecd4"   # green-tint
    if pct >= 90:  return "#fde9c8"   # amber-tint
    return "#fdd8d8"                  # red-tint


def color_delta(curr: Optional[float], prior: Optional[float]) -> str:
    """Text color for LM/LY delta: positive=green, negative=red, zero/NaN=muted."""
    if curr is None or prior is None or prior == 0:
        return "#7a6a50"
    pct = (curr - prior) / abs(prior) * 100
    if pct >  0.1: return "#1a7a3e"
    if pct < -0.1: return "#8b1a1a"
    return "#7a6a50"


# ─── HTML email build ───────────────────────────────────────────────────
# Inline CSS so Gmail / Outlook render correctly. No external assets,
# no JS, no <link> — just <style> in <head> + inline `style="..."` on
# elements that need it (Gmail strips some <style> rules).
_TABLE_CSS = (
    "width:100%;border-collapse:collapse;font-family:'Helvetica',"
    "Arial,sans-serif;font-size:13px;color:#3e2f1c;"
    "border:1px solid #d6ccba;border-radius:8px;overflow:hidden;"
    "margin:8px 0 18px 0;"
)
_TH_CSS = (
    "background:linear-gradient(180deg,#004A2B 0%,#2E7D32 100%);"
    "color:#FBF5EA;padding:9px 10px;text-align:left;font-weight:700;"
    "letter-spacing:0.3px;font-size:11px;text-transform:uppercase;"
    "border-bottom:2px solid #AB8743;"
)
_TD_CSS_BASE = (
    "padding:8px 10px;border-bottom:1px solid #ead9b5;"
    "color:#1a1a1a;vertical-align:middle;"
)


def _td(value: str, *, bg: str = "", weight: str = "500",
        color: str = "#1a1a1a", align: str = "right") -> str:
    extra = (f"background-color:{bg};" if bg else "")
    return (f'<td style="{_TD_CSS_BASE}font-weight:{weight};'
            f'color:{color};text-align:{align};{extra}">{value}</td>')


def _render_block(title: str, subtitle: str,
                  cur: Dict[str, Tuple[float, float]],
                  lm:  Dict[str, Tuple[float, float]],
                  ly:  Dict[str, Tuple[float, float]]) -> str:
    """One window's table — header + 5 GEO rows + TOTAL row at the top.
    cur/lm/ly are {geo: (act, bud)} dicts. LM/LY supply the prior
    actual to compute the delta % column."""
    # Aggregate totals
    total_cur = totals_row(cur)
    total_lm  = totals_row(lm)
    total_ly  = totals_row(ly)

    # Build header
    rows_html = [
        f'<tr>'
        f'<th style="{_TH_CSS}text-align:left;">GEO</th>'
        f'<th style="{_TH_CSS}text-align:right;">Actual</th>'
        f'<th style="{_TH_CSS}text-align:right;">Budget</th>'
        f'<th style="{_TH_CSS}text-align:right;">% Achv</th>'
        f'<th style="{_TH_CSS}text-align:right;">vs LM</th>'
        f'<th style="{_TH_CSS}text-align:right;">vs LY</th>'
        f'</tr>'
    ]

    def _row(label: str,
             cur_pair: Tuple[float, float],
             lm_pair: Tuple[float, float],
             ly_pair: Tuple[float, float],
             *, bold: bool = False) -> str:
        cur_act, cur_bud = cur_pair
        lm_act, _        = lm_pair
        ly_act, _        = ly_pair
        ach_bg = color_ach(cur_act, cur_bud)
        lm_col = color_delta(cur_act, lm_act)
        ly_col = color_delta(cur_act, ly_act)
        weight = "700" if bold else "500"
        # Subtle highlight band on TOTAL row
        row_bg = "background-color:#EDE8DC;" if bold else ""
        return (
            f'<tr style="{row_bg}">'
            f'<td style="{_TD_CSS_BASE}font-weight:{weight};color:#004A2B;'
            f'text-align:left;letter-spacing:0.3px;">{label}</td>'
            + _td(fmt_inr(cur_act), weight=weight)
            + _td(fmt_inr(cur_bud), weight=weight, color="#6b4a23")
            + _td(fmt_pct(cur_act, cur_bud), bg=ach_bg, weight="700")
            + _td(fmt_delta_pct(cur_act, lm_act), weight=weight, color=lm_col)
            + _td(fmt_delta_pct(cur_act, ly_act), weight=weight, color=ly_col)
            + f'</tr>'
        )

    # TOTAL row at top of each block for quick scan
    rows_html.append(_row("TOTAL", total_cur, total_lm, total_ly, bold=True))
    for g in GEO_BUCKETS:
        rows_html.append(_row(g, cur[g], lm[g], ly[g]))

    return (
        f'<div style="margin:18px 0 6px 0;">'
        f'<div style="font-size:14px;font-weight:700;color:#004A2B;'
        f'letter-spacing:0.5px;text-transform:uppercase;'
        f'border-left:3px solid #AB8743;padding-left:10px;">{title}</div>'
        f'<div style="font-size:11px;color:#7a6a50;margin:2px 0 6px 13px;">'
        f'{subtitle}</div>'
        f'</div>'
        f'<table style="{_TABLE_CSS}">'
        + "".join(rows_html) +
        f'</table>'
    )


def build_email_html(data: Dict[str, Dict[str, Tuple[float, float]]],
                     windows: Dict[str, Tuple[date, date]]) -> str:
    """Compose the full HTML body."""
    def fmt_range(d1: date, d2: date) -> str:
        if d1 == d2:
            return d1.strftime("%d %b %Y")
        return f"{d1.strftime('%d %b')} → {d2.strftime('%d %b %Y')}"

    snapshot_ist = datetime.now(IST).strftime("%d %b %Y · %H:%M IST")

    # Headline strip — top of email
    mtd_total = totals_row(data["mtd"])
    yest_total = totals_row(data["yest"])
    l7d_total = totals_row(data["l7d"])
    mtd_lm_total = totals_row(data["mtd_lm"])
    mtd_ly_total = totals_row(data["mtd_ly"])

    def _headline_cell(label: str, value: str, sub: str) -> str:
        return (
            f'<td style="padding:14px 18px;background:#FBF5EA;'
            f'border:1px solid #d6ccba;border-radius:8px;'
            f'vertical-align:top;min-width:170px;">'
            f'<div style="font-size:10px;font-weight:700;letter-spacing:1.5px;'
            f'color:#AB8743;text-transform:uppercase;margin-bottom:4px;">'
            f'{label}</div>'
            f'<div style="font-size:20px;font-weight:700;color:#004A2B;'
            f'margin:2px 0;">{value}</div>'
            f'<div style="font-size:11px;color:#7a6a50;">{sub}</div>'
            f'</td>'
        )

    headline_table = (
        f'<table style="border-collapse:separate;border-spacing:10px;'
        f'margin:8px -10px 16px -10px;"><tr>'
        + _headline_cell(
            "MTD",
            fmt_inr(mtd_total[0]),
            f"{fmt_pct(mtd_total[0], mtd_total[1])} vs Bud · "
            f"{fmt_delta_pct(mtd_total[0], mtd_lm_total[0])} vs LM")
        + _headline_cell(
            "Yesterday",
            fmt_inr(yest_total[0]),
            f"{fmt_pct(yest_total[0], yest_total[1])} vs Bud")
        + _headline_cell(
            "Last 7 Days",
            fmt_inr(l7d_total[0]),
            f"{fmt_pct(l7d_total[0], l7d_total[1])} vs Bud")
        + f'</tr></table>'
    )

    body = (
        f'<!DOCTYPE html><html><head><meta charset="UTF-8">'
        f'<style>body{{margin:0;padding:0;background:#f5efe0;}}</style>'
        f'</head>'
        f'<body style="background:#f5efe0;padding:20px;font-family:Helvetica,'
        f'Arial,sans-serif;color:#3e2f1c;">'
        f'<div style="max-width:900px;margin:0 auto;background:#FBF5EA;'
        f'padding:22px 26px;border-radius:12px;'
        f'box-shadow:0 2px 8px rgba(120,80,30,0.08);'
        f'border-top:4px solid #AB8743;">'

        # Header
        f'<div style="font-size:18px;font-weight:700;color:#004A2B;'
        f'letter-spacing:0.5px;">'
        f'VAHDAM · Daily Business Report</div>'
        f'<div style="font-size:13px;color:#7a6a50;margin-top:2px;'
        f'margin-bottom:14px;">Teas &amp; Botanicals · Snapshot {snapshot_ist}'
        f'</div>'

        # Headline KPI strip
        + headline_table +

        # Three blocks
        _render_block(
            "MTD",
            fmt_range(*windows["mtd"]) + " vs same elapsed days last month / last year",
            data["mtd"], data["mtd_lm"], data["mtd_ly"])
        + _render_block(
            "Yesterday",
            fmt_range(*windows["yest"]) + " vs same calendar day last month / last year",
            data["yest"], data["yest_lm"], data["yest_ly"])
        + _render_block(
            "Last 7 Days",
            fmt_range(*windows["l7d"]) + " vs same 7-day window last month / last year",
            data["l7d"], data["l7d_lm"], data["l7d_ly"])

        # Footer notes
        + f'<div style="font-size:11px;color:#7a6a50;margin-top:18px;'
        f'padding-top:12px;border-top:1px solid #d6ccba;line-height:1.5;">'
        f'<b>Scope:</b> Teas &amp; Botanicals only (Coffee &amp; Supplements '
        f'excluded). HP-prefixed AMZ categories (HP - Spices, HP - Teas …) '
        f'are Handpick products and are excluded.<br>'
        f'<b>GEO buckets:</b> ROE = DE + FR + IT + ES · AUS+UAE = Australia + UAE.<br>'
        f'<b>vs LM</b> = same window shifted one calendar month. '
        f'<b>vs LY</b> = same window shifted one calendar year.<br>'
        f'Generated by the Vahdam dashboard repo · GitHub Actions cron @ 15:30 IST.'
        f'</div>'

        f'</div></body></html>'
    )
    return body


# ─── SMTP send ──────────────────────────────────────────────────────────
def send_email(html_body: str, subject: str,
               sender: str, password: str,
               recipients: List[str]) -> None:
    """Send the HTML email via Gmail SMTP with STARTTLS."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = ", ".join(recipients)
    # Plain-text fallback for non-HTML clients. Minimal — the HTML
    # body is where the visual design lives.
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
        data: Dict[str, Dict[str, Tuple[float, float]]] = {}
        for key, (d1, d2) in windows.items():
            log.info("  · %-8s %s → %s", key, d1, d2)
            data[key] = fetch_window(conn, d1, d2)
    finally:
        conn.close()

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
