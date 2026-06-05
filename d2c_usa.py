"""
D2C USA dashboard — integrated into the main Vahdam dashboard as the
**D2C → USA** view. Entry point: ``render(run_query)``.

This module wraps the user's original D2C US source files
(``streamlit_app.py``, ``us_common.py`` and the per-category tab
dispatchers ``tab_overall.py``, ``tab_coffee.py``, ``tab_tea.py``,
``tab_supplements.py``) so they can run against the dashboard's
shared Snowflake connection without any changes to the source files.

Adapter trick
-------------
The user's code uses the Snowpark-style API:
    df = session.sql(sql).to_pandas()
The main dashboard exposes a different helper:
    df = run_query(sql)
The ``_D2CSession`` adapter below exposes a ``.sql(...).to_pandas()``
shape that delegates to ``run_query``, so the user's files run
unchanged.

Sub-tabs
--------
* 📊 OVERALL P&L  → ``tab_overall.render(session)``  → ``us_common.render_overall_pnl``
* ☕ COFFEE       → ``tab_coffee.render(session)``   → ``us_common.render_tab(session, "COFFEE")``
* 🍵 TEA          → ``tab_tea.render(session)``      → ``us_common.render_tab(session, "TEA")``
* 💊 SUPPLEMENTS  → ``tab_supplements.render(session)`` → ``us_common.render_tab(session, "SUPPLEMENTS")``
"""
import streamlit as st
import os
from datetime import datetime, timedelta


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


# ─── D2C theme — same beige palette the user's source uses ────────────
_D2C_USA_CSS = """
<style>
.d2c-usa-scope .stApp { background: transparent; }
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

/* USA sub-tab pills (Overall / Coffee / Tea / Supplements) */
.d2c-usa-subtabs [data-testid="stButton"] button {
    background: #FBF5EA !important;
    border: 1px solid #d6ccba !important;
    color: #4a3520 !important;
    font-weight: 600 !important;
    border-radius: 8px !important;
    padding: 8px 14px !important;
}
.d2c-usa-subtabs [data-testid="stButton"] button[kind="primary"] {
    background: linear-gradient(180deg, #8b5a2b 0%, #b58a4b 100%) !important;
    color: #fff8e8 !important;
    border: 1px solid #6b3f17 !important;
    box-shadow: 0 2px 6px rgba(120,80,30,0.18) !important;
}
</style>
"""


def render(run_query):
    """Entry point called from app.py. Renders the USA D2C dashboard
    using the user's source modules via the session adapter."""

    st.markdown(_D2C_USA_CSS, unsafe_allow_html=True)
    st.markdown('<div class="page-title">D2C &mdash; United States</div>',
                unsafe_allow_html=True)
    snapshot_time = datetime.now().strftime("%d %b %Y · %H:%M:%S")
    st.markdown(
        f'<div class="page-sub">Snapshot {snapshot_time} '
        f'&nbsp;·&nbsp; Currency: <b>USD ($)</b> '
        f'&nbsp;·&nbsp; Source: Shopify USA + Meta Ads + Google Ads'
        f'</div>',
        unsafe_allow_html=True)

    st.info(
        "Four views: **Overall P&L** (cross-category P&L), **Coffee**, "
        "**Tea & Botanicals**, **Supplements**. Each category view has "
        "Ad Spend, Meta Performance, Revenue, ROAS · CR · AOV, P&L, "
        "Cohort LTV, and Subscription Retention. Switch between them "
        "with the pills below."
    )

    # ── SUB-TAB SELECTOR (OVERALL / COFFEE / TEA / SUPPLEMENTS) ──────
    if "d2c_usa_active_tab" not in st.session_state:
        st.session_state.d2c_usa_active_tab = "OVERALL"

    st.markdown('<div class="d2c-usa-subtabs">', unsafe_allow_html=True)
    _tabs = [
        ("OVERALL",     "📊 Overall P&L"),
        ("COFFEE",      "☕ Coffee"),
        ("TEA",         "🍵 Tea & Botanicals"),
        ("SUPPLEMENTS", "💊 Supplements"),
    ]
    _stc = st.columns(len(_tabs), gap="small")
    for _i, (_key, _label) in enumerate(_tabs):
        with _stc[_i]:
            if st.button(_label,
                         use_container_width=True,
                         key=f"d2c_usa_subtab_{_key}",
                         type=("primary" if st.session_state.d2c_usa_active_tab == _key
                               else "secondary")):
                st.session_state.d2c_usa_active_tab = _key
                st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown("---")

    # ── Dispatch to the user's tab module via the session adapter ────
    session = _D2CSession(run_query)
    active = st.session_state.d2c_usa_active_tab
    try:
        if active == "OVERALL":
            import tab_overall
            tab_overall.render(session)
        elif active == "COFFEE":
            import tab_coffee
            tab_coffee.render(session)
        elif active == "TEA":
            import tab_tea
            tab_tea.render(session)
        elif active == "SUPPLEMENTS":
            import tab_supplements
            tab_supplements.render(session)
    except Exception as _err:
        st.error(f"D2C USA — {active} tab failed to render: "
                 f"{type(_err).__name__}: {_err}")
