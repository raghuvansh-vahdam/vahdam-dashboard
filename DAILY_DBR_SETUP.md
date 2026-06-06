# Daily DBR Email — Setup Guide

The Daily DBR Email is a scheduled GitHub Actions job that sends a
Teas & Botanicals P&L summary to a list of Vahdam team members at
**15:30 IST every day** (just after the 3 PM Snowflake refresh).

This guide covers the one-time setup. Once configured, the job runs
itself — no Streamlit Cloud dependency, no servers to babysit.

---

## 1. Generate a Gmail App Password

Gmail SMTP rejects regular account passwords for security. You need
a 16-character **App Password** tied to a specific app.

### Steps

1. Open the Google Account that should be the **FROM** address
   (e.g. `dashboard@vahdam.com` or any Vahdam Gmail account).
2. Go to **myaccount.google.com → Security**.
3. Confirm **2-Step Verification** is on (App Passwords are only
   available once 2SV is enabled).
4. Search for **App passwords** in the search bar at the top, or
   go directly: <https://myaccount.google.com/apppasswords>.
5. Type a name like `Vahdam Daily DBR` and click **Create**.
6. Copy the 16-character code (it'll look like
   `abcd efgh ijkl mnop` — spaces don't matter, paste as-is).

> ⚠️ Save this code somewhere safe. Google only shows it once.
> If you lose it, generate a new one — the old one stops working.

---

## 2. Add GitHub Secrets

Repo → **Settings → Secrets and variables → Actions → New repository secret**.

Add all eight secrets below. The Snowflake ones reuse the same
credentials the dashboard uses on Streamlit Cloud, so check the
existing dashboard config to copy them over.

| Secret name              | Example value                              | Notes |
|--------------------------|--------------------------------------------|-------|
| `SNOWFLAKE_ACCOUNT`      | `xy12345.ap-south-1`                       | Same as dashboard |
| `SNOWFLAKE_USER`         | `VAHDAM_DASHBOARD`                         | Same as dashboard |
| `SNOWFLAKE_PASSWORD`     | (the Snowflake user's password)            | Same as dashboard |
| `SNOWFLAKE_WAREHOUSE`    | `COMPUTE_WH`                               | Same as dashboard |
| `SNOWFLAKE_ROLE`         | `VAHDAM_READER`                            | Same as dashboard |
| `SNOWFLAKE_DATABASE`     | `VAHDAM_DB`                                | Same as dashboard |
| `SNOWFLAKE_SCHEMA`       | `MAPLEMONK`                                | Same as dashboard |
| `DBR_GMAIL_USER`         | `dashboard@vahdam.com`                     | The FROM address |
| `DBR_GMAIL_APP_PASSWORD` | `abcd efgh ijkl mnop`                      | From step 1 |
| `DBR_RECIPIENTS`         | `alice@vahdam.com,bob@vahdam.com,…`        | Comma-separated, no spaces required |

---

## 3. Verify the schedule

The workflow lives at `.github/workflows/daily-dbr.yml`. It runs on:

```yaml
schedule:
  - cron: "0 10 * * *"   # 10:00 UTC = 15:30 IST
```

GitHub Actions cron uses UTC. 15:30 IST = 10:00 UTC year-round
(India doesn't observe DST). No need to adjust seasonally.

> ℹ️ GitHub Actions can delay scheduled jobs by 5–15 minutes during
> peak times — that's normal. The email will land somewhere between
> 15:30 and 15:45 IST.

---

## 4. Test before the first scheduled run

You can trigger the workflow manually to verify everything works
before it goes live tomorrow at 15:30 IST.

### Dry-run (no email sent — just builds the HTML and prints it)

1. Repo → **Actions** tab → **Daily DBR Email** in the left sidebar.
2. Click **Run workflow** (right side).
3. Tick the **Dry run** checkbox → **Run workflow**.
4. Wait ~1 minute, then open the run.
5. The HTML body will be printed to the **Send Daily DBR** step's
   log output. Copy it into an `.html` file locally to preview.

### Real run (sends actual email)

1. Same as above but **leave the Dry run checkbox unticked**.
2. Recipients in `DBR_RECIPIENTS` will receive the email immediately.

---

## 5. Modify the recipient list later

Just edit the `DBR_RECIPIENTS` secret. No code change, no redeploy.
Comma-separated emails:

```
alice@vahdam.com,bob@vahdam.com,carol@vahdam.com
```

Spaces around commas are tolerated.

---

## 6. What's in the email

* **Headline strip** (3 cards): MTD, Yesterday, Last 7 Days revenue
  totals with % vs Budget and (for MTD) % vs LM.
* **Three blocks** (one per window). Each block has a table with:
  * Rows: `TOTAL`, `USA`, `UK`, `CA`, `ROE`, `AUS+UAE`
  * Columns: Actual, Budget, % Achv, vs LM, vs LY
  * Cells colored green/amber/red by % vs Budget; green/red text for LM/LY deltas.

* **Scope (footer)**: Teas & Botanicals only. Coffee + Supplements
  excluded. HP-prefixed AMZ_CATEGORY rows (Handpick products) also
  excluded.

* **GEO buckets**:
  * ROE = DE + FR + IT + ES
  * AUS+UAE = AUS + UAE combined
  * India and Mexico are excluded (matches dashboard's `GEO_EXCL` rule).

---

## 7. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| GitHub Actions shows ❌ on the job | Missing or wrong secret | Check the **Send Daily DBR** step's log — usually points at the missing var. |
| `smtplib.SMTPAuthenticationError` | Wrong app password, or 2SV not enabled | Regenerate the app password (step 1). |
| Email arrives but tables are empty | Snowflake query returned no rows for the date window | Check yesterday actually has data loaded. The 3:30 IST schedule assumes 3 PM refresh is done. |
| Recipients didn't get it | Gmail spam folder, or recipient typo in the secret | Check recipient inbox + spam; verify the `DBR_RECIPIENTS` secret value. |
| Want to pause for a holiday | Don't delete the workflow — just disable it | Actions tab → Daily DBR Email → "⋯" menu → **Disable workflow**. Re-enable later. |

---

## 8. Cost

GitHub Actions free tier: **2,000 minutes/month** of compute for
private repos. This job uses **<1 minute** per run × 30 days =
**~30 minutes/month**. Effectively free.

Gmail SMTP: free up to **500 emails/day** per sender. We send 1.
