import us_common

def render(session):
    # Cross-category MoM+YoY revenue summary (Coffee / Tea / Supplements)
    # rendered above the full P+L so the OVERALL tab opens with the headline.
    us_common.render_category_revenue(session)
    us_common.render_overall_pnl(session)