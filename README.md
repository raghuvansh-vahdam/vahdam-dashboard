# Vahdam Amazon P&L Dashboard

A Streamlit dashboard for analyzing Vahdam's Amazon P&L across GEOs, sub-categories, and ASINs. Connects directly to Snowflake.

## Features

- **Overview**: GEO × Channel breakdown with KPI cards (Revenue vs Budget, CM1%, ACoS%, CM2%, CM2 Absolute).
- **Sub-Category drill-down**: Click a GEO TOTAL row to see sub-category performance for that GEO.
- **ASIN drill-down**: Click a sub-category row to see ASIN-level P&L, ad performance, and a CM2-coloured bubble chart.
- **P&L Statement**: Full waterfall (Sales → COGS → CM1 → … → CM2) with budget variance, daily trend chart, and category breakdown.
- **Quick presets**: MTD, Last 30/60/90 Days, or custom date range.
- **SKU/ASIN search**: Search across ASIN and product description from the sidebar.
- **CSV exports** on every key table.

## Local development

1. Clone the repo and create a virtual environment:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate          # Windows
   source .venv/bin/activate        # macOS/Linux
   pip install -r requirements.txt
   ```

2. Copy the secrets template and fill in real values:
   ```bash
   copy .streamlit\secrets.toml.example .streamlit\secrets.toml
   ```
   Edit `.streamlit/secrets.toml` with your Snowflake credentials. This file is gitignored and will never be committed.

3. Run the app:
   ```bash
   streamlit run app.py
   ```

## Deploying to Streamlit Community Cloud

1. Push this repo to GitHub (see "First-time setup" below).
2. Go to <https://share.streamlit.io> and sign in with the GitHub account that owns the repo.
3. Click **New app**, pick this repo, set the main file to `app.py`, and click **Deploy**.
4. Once deployed, open **Settings → Secrets** and paste the contents of your local `secrets.toml` (the `[snowflake]` block).
5. Open **Settings → Sharing** and set the app to **Private**, then add teammate emails to the viewer list.

## First-time GitHub setup

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/<your-user>/vahdam-dashboard.git
git push -u origin main
```

Create the repo as **Private** on GitHub before running `git remote add`.

## File structure

```
vahdam_dashboard/
├── app.py                          # Main dashboard
├── requirements.txt                # Python dependencies
├── README.md                       # This file
├── vahdam_logo.webp                # Sidebar logo
├── .gitignore                      # Keeps secrets out of git
└── .streamlit/
    ├── config.toml                 # Brand theme (committed)
    ├── secrets.toml                # Real credentials (gitignored)
    └── secrets.toml.example        # Template (committed)
```

## Snowflake table

The dashboard reads from `vahdam_db.maplemonk.vahdam_amazon_pnl_overall_fy27_onwards` and `vahdam_db.maplemonk.vahdam_amazon_marketing`. P&L column names are discovered dynamically via `information_schema.columns`, so missing columns degrade gracefully to "—" rather than erroring.
